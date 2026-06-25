# Using Microsoft's official Playwright image means the OS-level Chromium
# dependencies (fonts, codecs, etc. — historically the most fragile part of
# setting this project up manually, see the README's note about venvs not
# surviving a zip/unzip across OSes) are already handled. We still run
# `playwright install` below to fetch the exact browser build matching
# whatever playwright version pip installs, since requirements.txt pins
# with '>=' rather than an exact version.
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# requirements.txt pins playwright with '>=', so pip could install a newer
# release than whatever this base image's Chromium build matches — always
# re-run install (not best-effort) so the browser actually matches whatever
# playwright version pip just installed, rather than risking a silent
# "Executable doesn't exist" failure at runtime.
RUN python3 -m playwright install --with-deps chromium

COPY . .

# Outputs (screenshots, videos, reports, the SQLite history) should live on
# a mounted volume in real usage — see the `docker run -v` example in
# README — so a container restart doesn't wipe your run history.
RUN mkdir -p outputs/reports outputs/videos outputs/tests outputs/screenshots \
             outputs/prds outputs/db outputs/worker_logs

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

WORKDIR /app/api
CMD ["python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]