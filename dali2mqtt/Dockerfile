ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System + build dependencies for python-dali / hidapi / pyusb
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-dev \
        build-essential \
        pkg-config \
        git \
        libhidapi-hidraw0 \
        libhidapi-dev \
        libusb-1.0-0 \
        libusb-1.0-0-dev \
        libudev-dev \
    && rm -rf /var/lib/apt/lists/*

# Isolated virtualenv (Debian bookworm is PEP-668 externally managed)
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /opt/dali2mqtt

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app/ ./app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
