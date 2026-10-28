# syntax=docker/dockerfile:1.7
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml ./
COPY src ./src
COPY scripts/ContainerHealthCheck.java /tmp/ContainerHealthCheck.java
# Optional secrets support managed build proxies; neither secret enters a layer.
RUN --mount=type=cache,target=/root/.m2 \
    --mount=type=secret,id=maven_settings \
    --mount=type=secret,id=java_truststore \
    if [ -f /run/secrets/java_truststore ]; then \
      export MAVEN_OPTS="$MAVEN_OPTS -Djavax.net.ssl.trustStore=/run/secrets/java_truststore"; \
    fi; \
    if [ -f /run/secrets/maven_settings ]; then \
      mvn -s /run/secrets/maven_settings -B -ntp -DskipTests package; \
    else \
      mvn -B -ntp -DskipTests package; \
    fi
RUN javac --release 21 -d /tmp/healthcheck /tmp/ContainerHealthCheck.java

FROM eclipse-temurin:21-jre AS runtime
WORKDIR /app
RUN groupadd --gid 10001 onboarding && \
    useradd --uid 10001 --gid onboarding --no-create-home onboarding
COPY --from=build --chown=onboarding:onboarding /build/target/practice-0.0.1-SNAPSHOT.jar /app/app.jar
COPY --from=build --chown=onboarding:onboarding /tmp/healthcheck /app/healthcheck
USER onboarding
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=4 \
    CMD ["java", "-cp", "/app/healthcheck", "ContainerHealthCheck"]
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=70", "-jar", "/app/app.jar"]
