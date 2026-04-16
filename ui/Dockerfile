# Stage 1: Build
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# Pass API endpoint at build time (can be overridden at runtime via Settings page)
ARG VITE_API_ENDPOINT=http://localhost:8080
ENV VITE_API_ENDPOINT=$VITE_API_ENDPOINT

RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
