# Movie Post-Credits & Easter Eggs Backend with a minimal frontend

A long time ago, I took part in a fronend hackathon and we built an app that queried movie db and community sourced with a poll to decide if the movie had an ending credit. I decided with the help of AI to build a backend API and a minimal frontend to build on that. In this repo, we do the following

- Run a daily batch job which queries all the latest movies in the theatre
- For each movie, we search some cool subreddits like `r/moviedetail` and imdb trivia and goofs
- We send this info to OpenAI and decide if the movie has ending credits and any easter eggs.


## Screenshots

[In theatre](./images/home.png)
[Recent Search](./images/recent.png)