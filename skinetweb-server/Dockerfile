FROM node:22.22.2-alpine

# kaggle CLI (Python package) — needed for one-time ISIC dataset download at startup.
# Pinned to 2.1.2: newer 2.2.x routes dataset downloads to an API endpoint that
# rejects legacy username/key auth with 403. 2.1.2 uses the REST path that works.
# 2.1.2 imports `six` without declaring it as a dependency; it used to arrive
# transitively, so install it explicitly.
RUN apk add --no-cache python3 py3-pip \
 && pip3 install --no-cache-dir --break-system-packages kaggle==2.1.2 six==1.17.0

WORKDIR /app
COPY ./package*.json ./
RUN npm i

COPY . .

RUN npm run build
CMD ["npm", "run", "start"]
