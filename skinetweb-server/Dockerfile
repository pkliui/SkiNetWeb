FROM node:22.22.2-alpine

WORKDIR /app
COPY skinetweb-server/package*.json ./
RUN npm i

COPY skinetweb-server/ .
COPY isic-examples/manifest.json ./isic-manifest.json

RUN npm run build
CMD ["npm", "run", "start"]
