FROM node:22.22.2-alpine

RUN apk add --no-cache python3 py3-pip && \
    pip3 install --break-system-packages kaggle

WORKDIR /app
COPY ./package*.json ./
RUN npm i

COPY . .

RUN npm run build
CMD ["npm", "run", "start"]
