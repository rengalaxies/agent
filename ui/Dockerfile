FROM nginx:1.27-alpine
COPY ui/index.html /usr/share/nginx/html/index.html
COPY ui/nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
