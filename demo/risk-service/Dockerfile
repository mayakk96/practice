FROM python:3.13-slim
WORKDIR /app
COPY --chown=65532:65532 --chmod=0444 server.py ./server.py
USER 65532:65532
EXPOSE 8090
CMD ["python", "-u", "server.py"]
