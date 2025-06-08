from fastapi import FastAPI, HTTPException, Response, Depends
from typing import Optional
from helper.vidsrc_extractor import VidSrcExtractor
from fastapi.middleware.cors import CORSMiddleware
import logging
import os
import requests
import time
import sqlite3
import traceback

app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Add CORS middleware
origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency
def get_vidsrc_extractor() -> VidSrcExtractor:
    return VidSrcExtractor()

# SQLite database initialization
DATABASE_FILE = "stream_cache.db"

def initialize_database():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS stream_cache (
                      imdb_id TEXT PRIMARY KEY,
                      stream_url TEXT
                   )''')
    conn.commit()
    conn.close()

initialize_database()

def insert_stream(imdb_id, stream_url):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''INSERT OR REPLACE INTO stream_cache (
                      imdb_id, stream_url)
                      VALUES (?, ?)''',
                   (imdb_id, stream_url))
    conn.commit()
    conn.close()

def get_stream_from_database(imdb_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''SELECT stream_url FROM stream_cache
                      WHERE imdb_id=?''',
                   (imdb_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    else:
        return None

def delete_stream_from_database(imdb_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''DELETE FROM stream_cache WHERE imdb_id=?''', (imdb_id,))
    conn.commit()
    conn.close()
    
@app.get("/")
def health_check():
    return {"status": "ok"}

@app.get("/stream/{imdb_id}", response_class=Response)
async def get_stream_content(
    imdb_id: str,
    vse: VidSrcExtractor = Depends(get_vidsrc_extractor),
):
    logging.info(f"📌 Stream request started for IMDb ID: {imdb_id}")

    # Intentar recuperar desde caché
    cached_stream = get_stream_from_database(imdb_id)
    if cached_stream:
        try:
            response = requests.head(cached_stream, timeout=5)
            if response.status_code == 200:
                response = requests.get(cached_stream, timeout=10)
                return Response(content=response.content, media_type="text/plain")
            else:
                logging.warning("Cached stream invalid. Removing from DB.")
                delete_stream_from_database(imdb_id)
        except requests.RequestException as e:
            logging.warning(f"Error accessing cached stream: {e}")
            delete_stream_from_database(imdb_id)

    # Obtener stream nuevo
    try:
        stream_url, subtitle = vse.get_vidsrc_stream("VidSrc PRO", "movie", imdb_id, "eng", None, None)
        logging.info(f"🔍 get_vidsrc_stream returned: {stream_url}, subtitle: {subtitle}")

        if not stream_url:
            raise HTTPException(status_code=404, detail="Stream not found")

        # Aquí hacemos la petición real al stream_url para inspeccionar
        response = requests.get(stream_url, timeout=10)

        # Logs para inspeccionar la respuesta
        logging.info(f"✅ Stream fetch status: {response.status_code}")
        content_type = response.headers.get("Content-Type")
        logging.info(f"Content-Type: {content_type}")

        # Imprimir primeros 500 caracteres del contenido (útil para m3u8, que es texto)
        snippet = response.text[:500] if response.text else "<No content>"
        logging.info(f"Content snippet:\n{snippet}")

        # Guardar contenido recibido en archivo para inspección manual
        with open("stream_output.m3u8", "wb") as f:
            f.write(response.content)
        logging.info("Stream content saved to 'stream_output.m3u8'")

        # Insertar en caché
        insert_stream(imdb_id, stream_url)

        # Devolver la respuesta al cliente
        return Response(content=response.content, media_type="text/plain")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logging.error(f"❌ Error in /stream: {e}")
        logging.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal server error")

