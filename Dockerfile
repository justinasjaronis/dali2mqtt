FROM python:3-alpine

WORKDIR /opt/app

RUN apk add --no-cache git

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python","-u", "./main.py"]