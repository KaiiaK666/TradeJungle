FROM node:20-alpine

WORKDIR /app
COPY package.json .
RUN npm install

COPY vite.config.js .
COPY index.html .
COPY src ./src

EXPOSE 5173
CMD ["npm", "run", "dev"]
