FROM python:3.12-slim
WORKDIR /service
COPY --chown=65534:65534 server.py ./
USER 65534:65534
EXPOSE 8091
HEALTHCHECK --interval=5s --timeout=3s --retries=10 CMD ["python", "-c", "import urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8091/health',timeout=2)"]
CMD ["python", "server.py"]
