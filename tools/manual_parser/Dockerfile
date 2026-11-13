FROM infiniflow/ragflow:v0.27.3

USER root
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/ragflow:/manual-parser \
    MANUAL_PARSER_DATA=/data \
    SAL_USE_VCLPLUGIN=svp

# DOC/DOCX conversion and page-faithful rendering. DeepDOC and its models are
# already contained in the pinned RAGFlow image; no database services are used.
RUN set -eux; \
    sed -i \
      -e 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' \
      -e 's|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|g' \
      /etc/apt/sources.list.d/ubuntu.sources; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i \
        -e 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' \
        -e 's|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|g' \
        /etc/apt/sources.list; \
    fi; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*; \
    apt-get clean; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends libreoffice-writer-nogui \
      fonts-crosextra-carlito fonts-crosextra-caladea fonts-wqy-microhei fonts-wqy-zenhei && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /ragflow
COPY deepdoc /ragflow/deepdoc
COPY rag /ragflow/rag
COPY common /ragflow/common
COPY tools/manual_parser /manual-parser

WORKDIR /manual-parser
RUN mkdir -p /data/jobs

EXPOSE 9392
VOLUME ["/data"]
HEALTHCHECK --interval=20s --timeout=5s --start-period=90s --retries=5 \
  CMD /ragflow/.venv/bin/python -c "import json,urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:9392/health',timeout=3))" || exit 1

ENTRYPOINT ["/ragflow/.venv/bin/python", "/manual-parser/server.py"]
