# imdb.py
from imdb import IMDb

# Create an instance of IMDb
ia = IMDb()

async def get_movie_details(title: str):
    """
    Fetch movie details from IMDb using IMDbPY
    """
    # IMDbPY is synchronous, so we run it in a thread to avoid blocking async
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_movie, title)


def _fetch_movie(title: str):
    """
    Synchronous fetch function for IMDbPY
    """
    movies = ia.search_movie(title)
    if not movies:
        return {"error": "Movie not found"}

    movie = movies[0]  # Take the first match
    ia.update(movie)

    return {
        "title": movie.get("title"),
        "year": movie.get("year"),
        "rating": movie.get("rating"),
        "genres": movie.get("genres"),
        "director": [str(d) for d in movie.get("director", [])],
        "cast": [str(a) for a in movie.get("cast", [])[:5]],  # first 5 actors
        "plot": movie.get("plot outline"),
        "runtime": movie.get("runtime"),
        "imdb_id": movie.movieID,
        "type": movie.get("kind"),
    }
