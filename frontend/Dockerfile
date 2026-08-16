FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html config.js config.example.js useMovieSearch.js MovieSearchComponent.js /usr/share/nginx/html/
EXPOSE 80
