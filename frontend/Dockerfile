# Development image: runs the Vite dev server. A production image comes in Phase 13.
FROM node:24-slim

WORKDIR /app

# Install dependencies first, so this layer is cached until the lock file changes
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
