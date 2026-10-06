FROM debian:bookworm-slim AS native
RUN apt-get update && apt-get install -y --no-install-recommends cmake ninja-build g++ git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY CMakeLists.txt ./
COPY cpp ./cpp
RUN cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build --target gridguard_ied gridguard_edge -j2
FROM python:3.12-slim-bookworm
RUN groupadd -g 10001 gridguard && useradd -u 10001 -g gridguard -m gridguard
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY gridguard ./gridguard
COPY --from=native /src/build/gridguard_ied /src/build/gridguard_edge ./build/
RUN mkdir -p /app/work && chown gridguard:gridguard /app/work
USER gridguard
CMD ["python", "-m", "uvicorn", "gridguard.api:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
