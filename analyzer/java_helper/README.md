# Java helper — the analyzer's Java-reading pass

A small standalone Java program (JavaParser + JavaSymbolSolver) that reads a Java
codebase and emits structured JSON facts. It is invoked as a subprocess by
`analyzer/java_extract.py` — the Python pipeline never parses Java itself, and the
helper never decides what a fact *means* (SQL table extraction and AWS read/write
classification happen on the Python side via sqlglot and botocore, the same
authorities the Python path uses).

## Build (once)

```
./build.sh
```

Requires a JDK (11+) and, the first time only, network access to Maven Central
(five jars are fetched into `jars/` and cached; versions are pinned in the script).
No Maven or Gradle needed — plain `javac`.

## Run (normally you don't — the pipeline does)

```
java -cp "build/classes:jars/*" JavaFactExtractor <source-root>
```

JSON on stdout: `entities`, `quads` (DEFINES / CALLS / EXPOSES_ENDPOINT /
READS_ENV_VAR), `aws_calls` (raw service+operation+literals), `sql_strings`
(raw SQL at type-anchored JDBC sites).

If Java files exist in an app but this helper isn't built, the analyzer **fails
loudly with build instructions** — a language is never silently skipped.

## What it extracts, and the rules it follows

- **Qualified names** come from each file's own `package` declaration, never from
  directory layout. Ids are the same canonical `Type:qualified-name` scheme the
  Python path uses (`Class:com.demo.svc.OrderService`, `Method:…OrderService.findOrder`).
- **Cross-file calls** resolve through JavaSymbolSolver (source roots + JRE).
  Unresolvable calls fall back to the same bare-name rule the Python parser uses:
  unique match → resolved edge; ambiguous → `Symbol:` with `resolved=false`. Never guessed.
- **Endpoints** (Spring `@GetMapping`/`@RequestMapping`…, JAX-RS `@GET`/`@Path`) are
  identified by their **import-resolved fully-qualified annotation name**, never by
  simple-name string matching. Class-level base paths are joined to method paths.
- **AWS calls** are detected by the receiver's **declared client type**
  (`software.amazon.awssdk.services.*` / `com.amazonaws.services.*`, instance calls
  only); builder-chain string literals are captured raw and validated on the Python
  side against the operation's real input shape from botocore's model.
- **SQL sites** are detected by resolved declaring type (`java.sql.*` methods with a
  `String` first parameter — by signature, not by a method-name list — plus
  `org.springframework.jdbc.*`). String concatenations keep their literal parts with
  `?` placeholders and are marked `resolved=false`.

## Known limits (slice 1, stated not hidden)

- External-library types resolve only through imports (dependency jars are not on
  the classpath); JavaSymbolSolver's own docs note generics/lambda resolution is not
  100% — unresolved facts are marked, never invented.
- AWS predicate mapping covers the same families as the Python path (S3 read/write,
  Lambda invoke, Step Function start); other AWS calls are recorded as Notes.
- SDK v1 positional constructor arguments are not mined for literals (symbolic instead).

## Dependency note for restricted environments

JavaParser is a third-party library (Apache-2.0), fetched from Maven Central at
build time. Whether the client environment can reach/approve it is an **open
question** tracked in `06_java_cucumber_karate_extension.md` — the jars can also be
vendored alongside this folder if fetching is not possible there.
