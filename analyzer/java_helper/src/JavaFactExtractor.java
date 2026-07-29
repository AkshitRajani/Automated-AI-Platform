/*
 * JavaFactExtractor — the Java side of the analyzer's Step-1 parser.
 *
 * Mirrors analyzer/extract.py for Java sources: deterministic, no LLM, no regex
 * over code. Structure comes from JavaParser's AST; cross-file call resolution
 * from JavaSymbolSolver (JavaParserTypeSolver over the app's own source roots +
 * ReflectionTypeSolver for the JRE). Where resolution fails, facts are marked
 * unresolved or omitted — never guessed.
 *
 * Output: JSON on stdout, consumed by analyzer/java_extract.py:
 *   entities      Module / Class / Method (canonical Type:qualified-name ids)
 *   quads         DEFINES / CALLS / EXPOSES_ENDPOINT / READS_ENV_VAR (final form)
 *   aws_calls     raw {service, operation, literals} — the PYTHON side classifies
 *                 read-vs-write via botocore's data model (no op lists here)
 *   sql_strings   raw SQL text found at type-anchored JDBC/Spring-JDBC call sites —
 *                 the PYTHON side extracts tables via sqlglot (no SQL parsing here)
 *
 * Principled boundaries (the guardrails from 06_java_cucumber_karate_extension.md):
 *   - Annotations are identified by their import-resolved fully-qualified name,
 *     never by simple-name string matching.
 *   - AWS calls are detected by the receiver's declared client type
 *     (software.amazon.awssdk.services.* / com.amazonaws.services.*), instance
 *     calls only; operations are NOT classified here.
 *   - SQL sites are detected by the resolved declaring type (java.sql.* with a
 *     String first parameter, or org.springframework.jdbc.*), never by variable
 *     naming conventions.
 *   - Qualified names derive from each file's own `package` declaration, never
 *     from directory layout.
 */

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.BodyDeclaration;
import com.github.javaparser.ast.body.CallableDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.ArrayInitializerExpr;
import com.github.javaparser.ast.expr.BinaryExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.MemberValuePair;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.expr.NormalAnnotationExpr;
import com.github.javaparser.ast.expr.SingleMemberAnnotationExpr;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.resolution.declarations.ResolvedMethodDeclaration;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.stream.Collectors;
import java.util.stream.Stream;

public class JavaFactExtractor {

    // ---- output records (kept as ordered maps for deterministic JSON) ------
    static final List<Map<String, Object>> entities = new ArrayList<>();
    static final List<Map<String, Object>> quads = new ArrayList<>();
    static final List<Map<String, Object>> awsCalls = new ArrayList<>();
    static final List<Map<String, Object>> sqlStrings = new ArrayList<>();
    static final TreeSet<String> entityIds = new TreeSet<>();
    // bare method name -> canonical Method ids (Python-parity fallback resolution)
    static final TreeMap<String, TreeSet<String>> symbols = new TreeMap<>();

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            System.err.println("usage: JavaFactExtractor <source-root>");
            System.exit(2);
        }
        Path root = Paths.get(args[0]).toAbsolutePath().normalize();
        List<Path> files = discover(root);

        // Phase A — cheap parse to learn each file's package, so source roots are
        // derived from the code's own package declarations (never path convention).
        JavaParser plain = new JavaParser();
        TreeSet<String> sourceRoots = new TreeSet<>();
        for (Path f : files) {
            com.github.javaparser.ParseResult<CompilationUnit> pr = plain.parse(f);
            // A file that doesn't parse is skipped entirely (mirror of the Python
            // path's SyntaxError skip) — error recovery must never leak half-facts.
            if (!pr.isSuccessful() || pr.getResult().isEmpty()) continue;
            Optional<CompilationUnit> cu = pr.getResult();
            String pkg = cu.get().getPackageDeclaration()
                    .map(p -> p.getNameAsString()).orElse("");
            Path dir = f.getParent();
            if (!pkg.isEmpty()) {
                Path suffix = Paths.get(pkg.replace('.', '/'));
                if (dir.endsWith(suffix)) {
                    dir = dir.getRoot().resolve(dir.subpath(0, dir.getNameCount() - suffix.getNameCount()));
                }
            }
            sourceRoots.add(dir.toString());
        }

        // Phase B — full parse with the symbol solver over the discovered roots.
        CombinedTypeSolver solver = new CombinedTypeSolver();
        solver.add(new ReflectionTypeSolver(true));            // JRE types only
        for (String sr : sourceRoots) solver.add(new JavaParserTypeSolver(Paths.get(sr)));
        ParserConfiguration cfg = new ParserConfiguration()
                .setSymbolResolver(new JavaSymbolSolver(solver));
        JavaParser parser = new JavaParser(cfg);

        List<CompilationUnit> units = new ArrayList<>();
        List<String> rels = new ArrayList<>();
        for (Path f : files) {
            com.github.javaparser.ParseResult<CompilationUnit> pr = parser.parse(f);
            if (!pr.isSuccessful() || pr.getResult().isEmpty()) continue;  // unparseable -> skip
            units.add(pr.getResult().get());
            rels.add(root.relativize(f).toString().replace('\\', '/'));
        }

        // Pass 1 — entities + DEFINES + the bare-name symbol table.
        TreeSet<String> modules = new TreeSet<>();
        for (int i = 0; i < units.size(); i++) collectEntities(units.get(i), rels.get(i), modules);

        // Pass 2 — per-method facts (calls, endpoints, env vars, AWS, SQL).
        for (int i = 0; i < units.size(); i++) collectFacts(units.get(i), rels.get(i));

        System.out.println(Json.obj(
                "entities", entities, "quads", quads,
                "aws_calls", awsCalls, "sql_strings", sqlStrings));
    }

    static List<Path> discover(Path root) throws IOException {
        try (Stream<Path> s = Files.walk(root)) {
            return s.filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> {
                        for (Path part : root.relativize(p)) {
                            String n = part.toString();
                            if (n.startsWith(".") || n.equals("node_modules") || n.equals("target")
                                    || n.equals("build") || n.equals("out")) return false;
                        }
                        return true;
                    })
                    .sorted().collect(Collectors.toList());
        }
    }

    // ---- pass 1: entities ---------------------------------------------------
    static void collectEntities(CompilationUnit cu, String rel, TreeSet<String> modules) {
        String pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
        String moduleId = "Module:" + (pkg.isEmpty() ? rel : pkg);
        if (modules.add(moduleId)) {
            entity(moduleId, "Module", pkg.isEmpty() ? rel : pkg, rel, 1, null);
        }
        for (TypeDeclaration<?> td : cu.findAll(TypeDeclaration.class)) {
            String qual = typeQualName(td, pkg);
            String cid = "Class:" + qual;
            entity(cid, "Class", qual, rel, line(td), endLine(td));
            quad(moduleId, "DEFINES", cid, true, 1.0, rel, line(td));
            // The class's own `implements` clause, symbol-resolved — the language-level
            // joint that connects an interface CALLS target to the implementing code.
            if (td instanceof com.github.javaparser.ast.body.ClassOrInterfaceDeclaration) {
                for (com.github.javaparser.ast.type.ClassOrInterfaceType it
                        : ((com.github.javaparser.ast.body.ClassOrInterfaceDeclaration) td).getImplementedTypes()) {
                    String iq = null;
                    try {
                        com.github.javaparser.resolution.types.ResolvedType rt = it.resolve();
                        if (rt.isReferenceType()) iq = rt.asReferenceType().getQualifiedName();
                    } catch (Exception ignored) { }
                    if (iq != null) {
                        quad(cid, "IMPLEMENTS", "Class:" + iq, true, 1.0, rel, line(td));
                    } else {
                        quad(cid, "IMPLEMENTS", "Class:" + it.getNameAsString(), false, 0.5, rel, line(td));
                    }
                }
            }
            for (BodyDeclaration<?> m : td.getMembers()) {
                if (!(m instanceof CallableDeclaration)) continue;   // methods + constructors
                CallableDeclaration<?> c = (CallableDeclaration<?>) m;
                String mq = qual + "." + c.getNameAsString();
                String mid = "Method:" + mq;
                if (entityIds.contains(mid)) {                       // overloads share one id
                    quadIfNew(cid, "DEFINES", mid, rel, line(c));
                    continue;
                }
                entity(mid, "Method", mq, rel, line(c), endLine(c));
                quad(cid, "DEFINES", mid, true, 1.0, rel, line(c));
                symbols.computeIfAbsent(c.getNameAsString(), k -> new TreeSet<>()).add(mid);
            }
        }
    }

    static String typeQualName(TypeDeclaration<?> td, String pkg) {
        List<String> parts = new ArrayList<>();
        Node n = td;
        while (n instanceof TypeDeclaration) {
            parts.add(0, ((TypeDeclaration<?>) n).getNameAsString());
            n = n.getParentNode().orElse(null);
        }
        return (pkg.isEmpty() ? "" : pkg + ".") + String.join(".", parts);
    }

    // ---- pass 2: facts -------------------------------------------------------
    static void collectFacts(CompilationUnit cu, String rel) {
        String pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
        for (TypeDeclaration<?> td : cu.findAll(TypeDeclaration.class)) {
            String qual = typeQualName(td, pkg);
            String basePath = classBasePath(cu, td);
            for (BodyDeclaration<?> m : td.getMembers()) {
                if (m instanceof MethodDeclaration) {
                    MethodDeclaration md = (MethodDeclaration) m;
                    String subject = "Method:" + qual + "." + md.getNameAsString();
                    endpoints(cu, md, basePath, subject, rel);
                    body(cu, md, subject, rel);
                } else if (m instanceof ConstructorDeclaration) {
                    String subject = "Method:" + qual + "." + ((ConstructorDeclaration) m).getNameAsString();
                    body(cu, (ConstructorDeclaration) m, subject, rel);
                } else if (m instanceof FieldDeclaration) {
                    // field initializers execute at construction -> facts belong to the class
                    body(cu, m, "Class:" + qual, rel);
                }
            }
        }
    }

    static void body(CompilationUnit cu, Node scope, String subject, String rel) {
        for (MethodCallExpr mce : scope.findAll(MethodCallExpr.class)) {
            int ln = line(mce);
            ResolvedMethodDeclaration rmd = null;
            try { rmd = mce.resolve(); } catch (Throwable ignored) { }

            if (rmd != null) {
                String declQual = rmd.declaringType().getQualifiedName();
                String pkg = rmd.declaringType().getPackageName();
                // System.getenv("X") — resolved against the JRE itself.
                if (declQual.equals("java.lang.System") && rmd.getName().equals("getenv")
                        && mce.getArguments().size() == 1) {
                    Lit v = literal(mce.getArgument(0));
                    if (v.resolved) quad(subject, "READS_ENV_VAR", "Parameter:" + v.text, true, 1.0, rel, ln);
                    continue;
                }
                // JDBC: any java.sql call whose first declared parameter is a String
                // (prepareStatement / execute / executeQuery / executeUpdate — by
                // signature, not by name list). sqlglot on the Python side is the
                // semantic filter for what is actually SQL.
                if (pkg.equals("java.sql") && rmd.getNumberOfParams() > 0
                        && rmd.getParam(0).describeType().equals("java.lang.String")
                        && !mce.getArguments().isEmpty()) {
                    Lit sql = literal(mce.getArgument(0));
                    if (!sql.text.isEmpty() && sql.hasLiteralPart) {
                        sqlString(subject, sql.text, sql.resolved, rel, ln);
                    }
                    continue;
                }
                if (pkg.startsWith("java.") || pkg.startsWith("javax.") || pkg.startsWith("jdk.")) {
                    continue;                                  // JRE-internal call -> not an app fact
                }
                String id = "Method:" + declQual + "." + rmd.getName();
                if (entityIds.contains(id)) {
                    quad(subject, "CALLS", id, true, 1.0, rel, ln);
                }
                continue;
            }

            // Unresolved (external library): anchor on the receiver's DECLARED type.
            String declType = scopeDeclaredType(cu, mce);
            if (declType != null) {
                String svc = awsService(declType);
                if (svc != null) {
                    Map<String, Object> call = new LinkedHashMap<>();
                    call.put("subject", subject);
                    call.put("service", svc);
                    call.put("operation", mce.getNameAsString());
                    call.put("literals", builderLiterals(mce));
                    call.put("file", rel);
                    call.put("line", ln);
                    awsCalls.add(call);
                    continue;
                }
                if (declType.startsWith("org.springframework.jdbc.") && !mce.getArguments().isEmpty()) {
                    Lit sql = literal(mce.getArgument(0));
                    if (sql.hasLiteralPart) sqlString(subject, sql.text, sql.resolved, rel, ln);
                    continue;
                }
            }

            // Python-parity fallback: bare name against the app's own symbol table.
            TreeSet<String> targets = symbols.get(mce.getNameAsString());
            if (targets != null && mce.getScope().isEmpty()) {
                if (targets.size() == 1) {
                    quad(subject, "CALLS", targets.first(), true, 1.0, rel, ln);
                } else {
                    quad(subject, "CALLS", "Symbol:" + mce.getNameAsString(), false, 0.5, rel, ln);
                }
            }
        }
    }

    // ---- endpoints (annotation FQN via imports — never simple-name matching) --
    static final String SPRING_WEB = "org.springframework.web.bind.annotation.";

    static String classBasePath(CompilationUnit cu, TypeDeclaration<?> td) {
        for (AnnotationExpr a : td.getAnnotations()) {
            String fqn = annotationFqn(cu, a);
            if (fqn == null) continue;
            if (fqn.equals(SPRING_WEB + "RequestMapping")) return annPath(a).text;
            if (fqn.equals("javax.ws.rs.Path") || fqn.equals("jakarta.ws.rs.Path")) return annPath(a).text;
        }
        return "";
    }

    static void endpoints(CompilationUnit cu, MethodDeclaration md, String base,
                          String subject, String rel) {
        for (AnnotationExpr a : md.getAnnotations()) {
            String fqn = annotationFqn(cu, a);
            if (fqn == null) continue;
            String verb = null;
            Lit path = null;
            if (fqn.startsWith(SPRING_WEB)) {
                String simple = fqn.substring(SPRING_WEB.length());
                if (simple.endsWith("Mapping")) {
                    String v = simple.substring(0, simple.length() - "Mapping".length()).toUpperCase();
                    verb = v.equals("REQUEST") ? requestMappingVerb(a) : v;
                    path = annPath(a);
                }
            } else if (fqn.startsWith("javax.ws.rs.") || fqn.startsWith("jakarta.ws.rs.")) {
                String simple = fqn.substring(fqn.lastIndexOf('.') + 1);
                if (List.of("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS").contains(simple)) {
                    verb = simple;
                    path = jaxrsMethodPath(cu, md);
                }
            }
            if (verb == null) continue;
            String full = joinPath(base, path.text);
            quad(subject, "EXPOSES_ENDPOINT", "APIEndpoint:" + verb + " " + full,
                    path.resolved, path.resolved ? 1.0 : 0.5, rel, line(md));
        }
    }

    static String requestMappingVerb(AnnotationExpr a) {
        if (a instanceof NormalAnnotationExpr) {
            for (MemberValuePair p : ((NormalAnnotationExpr) a).getPairs()) {
                if (p.getNameAsString().equals("method")) {
                    String t = p.getValue().toString();
                    int dot = t.lastIndexOf('.');
                    return (dot >= 0 ? t.substring(dot + 1) : t).toUpperCase();
                }
            }
        }
        return "GET";
    }

    static Lit jaxrsMethodPath(CompilationUnit cu, MethodDeclaration md) {
        for (AnnotationExpr a : md.getAnnotations()) {
            String fqn = annotationFqn(cu, a);
            if (fqn != null && (fqn.equals("javax.ws.rs.Path") || fqn.equals("jakarta.ws.rs.Path"))) {
                return annPath(a);
            }
        }
        return new Lit("", true, false);
    }

    static Lit annPath(AnnotationExpr a) {
        Expression v = null;
        if (a instanceof SingleMemberAnnotationExpr) v = ((SingleMemberAnnotationExpr) a).getMemberValue();
        else if (a instanceof NormalAnnotationExpr) {
            for (MemberValuePair p : ((NormalAnnotationExpr) a).getPairs()) {
                if (p.getNameAsString().equals("value") || p.getNameAsString().equals("path")) {
                    v = p.getValue();
                    break;
                }
            }
        }
        if (v == null) return new Lit("", true, false);
        if (v instanceof ArrayInitializerExpr) {
            List<Expression> vals = ((ArrayInitializerExpr) v).getValues();
            v = vals.isEmpty() ? null : vals.get(0);
            if (v == null) return new Lit("", true, false);
        }
        return literal(v);
    }

    static String joinPath(String base, String path) {
        String b = base == null ? "" : base.trim();
        String p = path == null ? "" : path.trim();
        if (b.isEmpty()) return p.isEmpty() ? "/" : p;
        if (p.isEmpty()) return b;
        return (b.endsWith("/") ? b.substring(0, b.length() - 1) : b)
                + (p.startsWith("/") ? p : "/" + p);
    }

    /** Resolve an annotation's fully-qualified name through the file's own import
     *  table (exact import > wildcard package > already-qualified). Never guesses. */
    static String annotationFqn(CompilationUnit cu, AnnotationExpr a) {
        String name = a.getNameAsString();
        if (name.contains(".")) return name;
        String exact = null;
        List<String> wildcards = new ArrayList<>();
        for (ImportDeclaration imp : cu.getImports()) {
            if (imp.isStatic()) continue;
            String in = imp.getNameAsString();
            if (imp.isAsterisk()) wildcards.add(in);
            else if (in.endsWith("." + name)) exact = in;
        }
        if (exact != null) return exact;
        if (wildcards.size() == 1) return wildcards.get(0) + "." + name;
        return null;                                          // ambiguous or local -> unknown
    }

    // ---- declared-type anchoring for external receivers ----------------------
    /** The declared type FQN of a call's receiver VARIABLE (param, local, field),
     *  resolved through the import table. Returns null for static/type receivers,
     *  unknown names, or ambiguity — a null means "no fact", never a guess. */
    static String scopeDeclaredType(CompilationUnit cu, MethodCallExpr mce) {
        Optional<Expression> scope = mce.getScope();
        if (scope.isEmpty()) return null;
        String var;
        if (scope.get() instanceof NameExpr) var = ((NameExpr) scope.get()).getNameAsString();
        else if (scope.get() instanceof FieldAccessExpr
                && ((FieldAccessExpr) scope.get()).getScope().isThisExpr())
            var = ((FieldAccessExpr) scope.get()).getNameAsString();
        else return null;

        String typeName = null;
        // nearest enclosing callable: parameters, then any local declarator
        Optional<Node> encl = mce.findAncestor(CallableDeclaration.class).map(n -> (Node) n);
        if (encl.isPresent()) {
            CallableDeclaration<?> c = (CallableDeclaration<?>) encl.get();
            for (Parameter p : c.getParameters()) {
                if (p.getNameAsString().equals(var)) typeName = p.getTypeAsString();
            }
            if (typeName == null) {
                for (VariableDeclarator vd : c.findAll(VariableDeclarator.class)) {
                    if (vd.getNameAsString().equals(var)) typeName = vd.getTypeAsString();
                }
            }
        }
        if (typeName == null) {                                // class fields
            Optional<TypeDeclaration> td = mce.findAncestor(TypeDeclaration.class);
            if (td.isPresent()) {
                for (FieldDeclaration fd : td.get().findAll(FieldDeclaration.class)) {
                    for (VariableDeclarator vd : fd.getVariables()) {
                        if (vd.getNameAsString().equals(var)) typeName = vd.getTypeAsString();
                    }
                }
            }
        }
        if (typeName == null) return null;
        int generic = typeName.indexOf('<');
        if (generic > 0) typeName = typeName.substring(0, generic);
        if (typeName.contains(".")) return typeName;
        String exact = null;
        List<String> wildcards = new ArrayList<>();
        for (ImportDeclaration imp : cu.getImports()) {
            if (imp.isStatic()) continue;
            if (imp.isAsterisk()) wildcards.add(imp.getNameAsString());
            else if (imp.getNameAsString().endsWith("." + typeName)) exact = imp.getNameAsString();
        }
        if (exact != null) return exact;
        if (wildcards.size() == 1) return wildcards.get(0) + "." + typeName;
        return null;
    }

    /** AWS service name iff the declared type is a service CLIENT (v2: …services.<svc>.XxxClient;
     *  v1: com.amazonaws.services.<svc>.* outside .model). Model/builder types don't count. */
    static String awsService(String fqn) {
        String v2 = "software.amazon.awssdk.services.";
        if (fqn.startsWith(v2) && !fqn.contains(".model.")) {
            String restPart = fqn.substring(v2.length());
            int dot = restPart.indexOf('.');
            if (dot > 0 && restPart.substring(dot + 1).endsWith("Client")) {
                return restPart.substring(0, dot);
            }
        }
        String v1 = "com.amazonaws.services.";
        if (fqn.startsWith(v1) && !fqn.contains(".model.")) {
            String restPart = fqn.substring(v1.length());
            int dot = restPart.indexOf('.');
            if (dot > 0) return restPart.substring(0, dot);
        }
        return null;
    }

    /** String literals from SDK-v2 builder chains inside the call's arguments:
     *  .bucket("x") -> {bucket: "x"}. Pure AST walk; the Python side maps these to
     *  the operation's real input-shape members via botocore. */
    static Map<String, Object> builderLiterals(MethodCallExpr mce) {
        Map<String, Object> out = new TreeMap<>();
        for (Expression arg : mce.getArguments()) {
            for (MethodCallExpr inner : arg.findAll(MethodCallExpr.class)) {
                if (inner.getArguments().size() == 1
                        && inner.getArgument(0) instanceof StringLiteralExpr) {
                    out.put(inner.getNameAsString(),
                            ((StringLiteralExpr) inner.getArgument(0)).getValue());
                }
            }
        }
        return out;
    }

    // ---- literals ------------------------------------------------------------
    static class Lit {
        final String text;
        final boolean resolved;         // fully literal
        final boolean hasLiteralPart;   // at least partly literal (concat case)
        Lit(String t, boolean r, boolean h) { text = t; resolved = r; hasLiteralPart = h; }
    }

    /** A string literal is resolved; a concat of literals and expressions keeps the
     *  literal parts with '?' placeholders (resolved=false); anything else is symbolic. */
    static Lit literal(Expression e) {
        if (e instanceof StringLiteralExpr) {
            return new Lit(((StringLiteralExpr) e).getValue(), true, true);
        }
        if (e instanceof BinaryExpr && ((BinaryExpr) e).getOperator() == BinaryExpr.Operator.PLUS) {
            Lit l = literal(((BinaryExpr) e).getLeft());
            Lit r = literal(((BinaryExpr) e).getRight());
            boolean any = l.hasLiteralPart || r.hasLiteralPart;
            // a concat of purely-literal parts (multi-line SQL style) is still fully
            // resolved; only a non-literal part degrades it
            return new Lit(l.text + r.text, l.resolved && r.resolved, any);
        }
        return new Lit("?", false, false);
    }

    // ---- record helpers -------------------------------------------------------
    static void entity(String id, String type, String name, String rel, Integer ls, Integer le) {
        if (!entityIds.add(id)) return;
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("id", id); e.put("type", type); e.put("name", name);
        e.put("file", rel); e.put("line_start", ls); e.put("line_end", le);
        entities.add(e);
    }

    static void quad(String s, String p, String o, boolean resolved, double conf,
                     String rel, Integer ln) {
        Map<String, Object> q = new LinkedHashMap<>();
        q.put("subject", s); q.put("predicate", p); q.put("object", o);
        q.put("resolved", resolved); q.put("confidence", conf);
        q.put("file", rel); q.put("line", ln);
        quads.add(q);
    }

    static void quadIfNew(String s, String p, String o, String rel, Integer ln) {
        for (Map<String, Object> q : quads) {
            if (q.get("subject").equals(s) && q.get("predicate").equals(p) && q.get("object").equals(o)) return;
        }
        quad(s, p, o, true, 1.0, rel, ln);
    }

    static void sqlString(String subject, String sql, boolean resolved, String rel, Integer ln) {
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("subject", subject); r.put("sql", sql); r.put("resolved", resolved);
        r.put("file", rel); r.put("line", ln);
        sqlStrings.add(r);
    }

    static Integer line(Node n) {
        return n.getRange().map(r -> r.begin.line).orElse(null);
    }

    static Integer endLine(Node n) {
        return n.getRange().map(r -> r.end.line).orElse(null);
    }

    // ---- minimal deterministic JSON writer (no external JSON dependency) ------
    static class Json {
        static String obj(Object... kv) {
            StringBuilder b = new StringBuilder("{");
            for (int i = 0; i < kv.length; i += 2) {
                if (i > 0) b.append(",");
                b.append(str((String) kv[i])).append(":").append(any(kv[i + 1]));
            }
            return b.append("}").toString();
        }

        static String any(Object v) {
            if (v == null) return "null";
            if (v instanceof String) return str((String) v);
            if (v instanceof Boolean || v instanceof Integer || v instanceof Long) return v.toString();
            if (v instanceof Double) {
                double d = (Double) v;
                return d == Math.floor(d) && !Double.isInfinite(d)
                        ? String.valueOf((long) d) : String.valueOf(d);
            }
            if (v instanceof Map) {
                StringBuilder b = new StringBuilder("{");
                boolean first = true;
                for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                    if (!first) b.append(",");
                    first = false;
                    b.append(str(String.valueOf(e.getKey()))).append(":").append(any(e.getValue()));
                }
                return b.append("}").toString();
            }
            if (v instanceof List) {
                StringBuilder b = new StringBuilder("[");
                boolean first = true;
                for (Object o : (List<?>) v) {
                    if (!first) b.append(",");
                    first = false;
                    b.append(any(o));
                }
                return b.append("]").toString();
            }
            return str(String.valueOf(v));
        }

        static String str(String s) {
            StringBuilder b = new StringBuilder("\"");
            for (char c : s.toCharArray()) {
                switch (c) {
                    case '"': b.append("\\\""); break;
                    case '\\': b.append("\\\\"); break;
                    case '\n': b.append("\\n"); break;
                    case '\r': b.append("\\r"); break;
                    case '\t': b.append("\\t"); break;
                    default:
                        if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                        else b.append(c);
                }
            }
            return b.append("\"").toString();
        }
    }
}
