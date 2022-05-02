FROM python:3

WORKDIR /opt/app

RUN apt-get update \
    && apt install -y git libhidapi-hidraw0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python","-u", "./main.py"]