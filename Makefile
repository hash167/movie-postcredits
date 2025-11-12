build-and-push-docker:
	docker buildx build --no-cache \
    --platform linux/amd64 \
    -t randomnumber20/movie-api:latest \
    --push .