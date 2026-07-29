#!/usr/bin/env bash
# Build the Java fact-extractor helper.
#
# Requires: JDK 11+ (javac/java) and network access to Maven Central the FIRST
# time (jars are cached in jars/ afterwards). No Maven/Gradle needed.
#
# Pinned versions — bump deliberately, never silently.
set -euo pipefail
cd "$(dirname "$0")"

JP_VERSION="3.26.2"
JAVASSIST_VERSION="3.30.2-GA"
GUAVA_VERSION="33.3.0-jre"            # JSS runtime dep (from javaparser-parent pom)
FAILUREACCESS_VERSION="1.0.2"         # guava's own runtime dep
MAVEN="https://repo1.maven.org/maven2"

mkdir -p jars build/classes

fetch() {  # fetch <group-path> <artifact> <version>
  local jar="jars/$2-$3.jar"
  if [ ! -f "$jar" ]; then
    echo "fetching $2 $3 ..."
    curl -fsSL -o "$jar" "$MAVEN/$1/$2/$3/$2-$3.jar"
  fi
}

fetch "com/github/javaparser" "javaparser-core" "$JP_VERSION"
fetch "com/github/javaparser" "javaparser-symbol-solver-core" "$JP_VERSION"
fetch "org/javassist" "javassist" "$JAVASSIST_VERSION"
fetch "com/google/guava" "guava" "$GUAVA_VERSION"
fetch "com/google/guava" "failureaccess" "$FAILUREACCESS_VERSION"

CP="jars/*"

javac -cp "$CP" -d build/classes src/JavaFactExtractor.java
echo "built: build/classes (classpath jars in jars/)"
