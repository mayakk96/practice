# Practice task API

A small REST API built with Java 21, Spring Boot 3.5, Spring Data JPA, and an embedded H2 database.

## Run it

Install a Java 21 JDK. The included Maven wrapper downloads Maven 3.9.16 on its first run; no separate Maven or database installation is needed.

From the repository directory:

```sh
./mvnw spring-boot:run
```

The server listens on port 8080. Stop it with Ctrl+C. On Windows, use `mvnw.cmd` instead of `./mvnw`.

## Try the API

Create a task:

```sh
curl -i -X POST http://localhost:8080/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"Learn Spring Boot","description":"Build a small API"}'
```

The response is `201 Created`, with a generated ID and a `Location` header:

```json
{"id":1,"title":"Learn Spring Boot","description":"Build a small API","completed":false}
```

List tasks, then read, update, and delete one. Replace `1` with the ID returned by your create request:

```sh
curl http://localhost:8080/api/tasks
curl http://localhost:8080/api/tasks/1

curl -X PUT http://localhost:8080/api/tasks/1 \
  -H 'Content-Type: application/json' \
  -d '{"title":"Learn Spring Boot","description":"Finished the API","completed":true}'

curl -i -X DELETE http://localhost:8080/api/tasks/1
```

| Method | Path | Successful response |
| --- | --- | --- |
| GET | `/api/tasks` | `200`, all tasks ordered by ID; `[]` when empty |
| POST | `/api/tasks` | `201`, the created task and its `Location` |
| GET | `/api/tasks/{id}` | `200`, the task |
| PUT | `/api/tasks/{id}` | `200`, the replaced task |
| DELETE | `/api/tasks/{id}` | `204`, no response body |

For POST and PUT, `title` is required, must contain non-whitespace text, and has a maximum length of 120 characters. Surrounding whitespace is removed before storage. `description` is optional and allows up to 2,000 characters. `completed` defaults to `false`.

PUT replaces all editable fields: omitting `description` clears it, and omitting `completed` sets it to `false`. Invalid requests return `400`; a missing task returns `404`. Errors use JSON Problem Details, with an `errors` field containing field-specific messages for validation failures.

## Database

The application creates its H2 database under `./data/tasks` relative to the working directory. Data survives application restarts, and the `data/` directory is ignored by Git. Set `TASK_DB_PATH` to an absolute path or a relative path beginning with `./` to use another location:

```sh
TASK_DB_PATH=./data/my-tasks ./mvnw spring-boot:run
```

## Test and package

```sh
./mvnw test
./mvnw verify
```

The integration tests exercise the HTTP request handling and actual database operations. They cover CRUD, request validation, defaults, list ordering, malformed JSON, and missing IDs. Tests use an isolated in-memory H2 database and do not touch your saved tasks.

To build and run an executable JAR:

```sh
./mvnw package
java -jar target/practice-0.0.1-SNAPSHOT.jar
```

This is a local learning application with no authentication. Hibernate updates the database schema automatically for development; production use would need explicit migrations and appropriate access controls.
