import re
import base64
import requests
from bs4 import BeautifulSoup
from typing import Optional

class VidSrcExtractor:
    def hunter_def(self, d, e, f) -> int:
        '''Used by self.hunter'''
        g = list("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/")
        h = g[0:e]
        i = g[0:f]
        d = list(d)[::-1]
        j = 0
        for c,b in enumerate(d):
            if b in h:
                j += h.index(b) * (e ** c)
    
        k = ""
        while j > 0:
            k = i[j % f] + k
            j = (j - (j % f)) // f
    
        return int(k) or 0
    
    def hunter(self, h, u, n, t, e, r) -> str:
        '''Decodes the common h,u,n,t,e,r packer'''
        r = ""
        i = 0
        while i < len(h):
            j = 0
            s = ""
            while h[i] != n[e]:
                s += h[i]
                i += 1
    
            while j < len(n):
                s = s.replace(n[j], str(j))
                j += 1
    
            r += ''.join(map(chr, [self.hunter_def(s, e, 10) - t]))
            i += 1
    
        return r

    def decode_src(self, encoded, seed) -> str:
        '''Decode hash found @ vidsrc.me embed page'''
        encoded_buffer = bytes.fromhex(encoded)
        decoded = ""
        for i in range(len(encoded_buffer)):
            decoded += chr(encoded_buffer[i] ^ ord(seed[i % len(seed)]))
        return decoded
    
    def decode_base64_url_safe(self, s) -> bytearray:
        standardized_input = s.replace('_', '/').replace('-', '+')
        return bytearray(base64.b64decode(standardized_input))

    def handle_vidsrc_stream(self, url: str, referer: str) -> Optional[str]:
        '''Extracts the actual HLS stream URL from vidsrc stream'''
        max_retries = 5
        headers = {"Referer": referer, "User-Agent": "Mozilla/5.0"}

        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    print(f"[Attempt {attempt+1}] Non-200 response: {response.status_code}")
                    continue

                # Buscamos el archivo .m3u8 codificado
                match = re.search(r'file:"([^"]+)"', response.text)
                if not match:
                    print(f"[Attempt {attempt+1}] No se encontró patrón file:\"...\" en la respuesta")
                    continue
                
                hls_url = match.group(1)
                # Eliminar partes problemáticas que puedan haber sido añadidas
                hls_url = re.sub(r'\/\/\S+?=', '', hls_url).replace('#2', '')

                # Intentamos decodificar el base64, si falla, intentamos siguiente intento
                try:
                    hls_url_decoded = base64.b64decode(hls_url).decode('utf-8')
                except Exception as e:
                    print(f"[Attempt {attempt+1}] Falló decodificación base64: {e}")
                    continue

                # Si la URL termina con "/list.m3u8", puede que necesite un pase adicional
                if hls_url_decoded.endswith("/list.m3u8"):
                    pass_path_match = re.search(r'var pass_path = "(.*?)";', response.text)
                    if pass_path_match and pass_path_match.group(1).startswith("//"):
                        pass_url = f"https:{pass_path_match.group(1)}"
                        # Realizamos la petición adicional para validar el pase
                        requests.get(pass_url, headers=headers)
                    return hls_url_decoded
                
                # Si no, devolvemos el link decodificado
                return hls_url_decoded

            except requests.RequestException as e:
                print(f"[Attempt {attempt+1}] Error de petición: {e}")

        print("[Error] Se alcanzó el máximo de intentos sin obtener la URL de stream.")
        return None

    def handle_2embed(self, url, source) -> Optional[str]:
        '''Currently not implemented, due to SSL issues'''
        print("[Warning] 2Embed handler not implemented.")
        return None

    def handle_multiembed(self, url, source) -> Optional[str]:
        '''Fallback handler used by vidsrc'''
        try:
            req = requests.get(url, headers={"Referer": source, "User-Agent": "Mozilla/5.0"})
            matches = re.search(r'escape\(r\)\)}\((.*?)\)', req.text)
            if not matches:
                print("[Error] Multiembed fetch failed, possible captcha or blocked request.")
                print(f"URL: {url}")
                return None

            # Parseamos los valores
            raw_values = matches.group(1).split(',')
            processed_values = []
            for val in raw_values:
                val = val.strip()
                if val.isdigit() or (val.startswith('-') and val[1:].isdigit()):
                    processed_values.append(int(val))
                elif val.startswith('"') and val.endswith('"'):
                    processed_values.append(val[1:-1])

            unpacked = self.hunter(*processed_values)
            hls_match = re.search(r'file:"([^"]+)"', unpacked)
            if hls_match:
                return hls_match.group(1)
            else:
                print("[Error] No se encontró archivo HLS en contenido desempaquetado.")
                return None
        except requests.RequestException as e:
            print(f"[Error] Request failed in multiembed handler: {e}")
            return None

    def fetch_best_subtitle_url(self, code: str, language: str) -> Optional[str]:
        '''Fetches highest scored subtitle from OpenSubtitles'''
        if "_" in code:
            code, se = code.split("_")
            season, episode = se.split('x')
            url = f"https://rest.opensubtitles.org/search/episode-{episode}/imdbid-{code}/season-{season}/sublanguageid-{language}"
        else:
            url = f"https://rest.opensubtitles.org/search/imdbid-{code}/sublanguageid-{language}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'X-User-Agent': 'trailers.to-UA',
        }
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                subs = response.json()
                if subs:
                    best_subtitle = max(subs, key=lambda x: x.get('score', 0))
                    return best_subtitle.get("SubDownloadLink")
        except Exception as e:
            print(f"[Error] Fallo al buscar subtítulos: {e}")
        return None

    def get_vidsrc_stream(self, name, media_type, code, language, season=None, episode=None) -> Optional[tuple]:
        provider = "imdb" if "tt" in code else "tmdb"
        url = f"https://vidsrc.me/embed/{media_type}?{provider}={code}"
        if season and episode:
            url += f"&season={season}&episode={episode}"

        print(f"Solicitando: {url}")
        try:
            req = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(req.text, "html.parser")

            # Obtenemos los servidores y sus hashes
            sources = {attr.text.strip(): attr.get("data-hash") for attr in soup.find_all("div", {"class": "server"})}
            source = sources.get(name)
            if not source:
                print(f"No se encontró fuente con nombre '{name}'. Fuentes disponibles: {', '.join(sources.keys())}")
                return None, None

            req_1 = requests.get(f"https://rcp.vidsrc.me/rcp/{source}", headers={"Referer": url, "User-Agent": "Mozilla/5.0"})
            soup_1 = BeautifulSoup(req_1.text, "html.parser")

            encoded = soup_1.find("div", {"id": "hidden"}).get("data-h")
            seed = soup_1.find("body").get("data-i")

            decoded_url = self.decode_src(encoded, seed)
            if decoded_url.startswith("//"):
                decoded_url = "https:" + decoded_url

            req_2 = requests.get(decoded_url, allow_redirects=False, headers={"Referer": f"https://rcp.vidsrc.me/rcp/{source}", "User-Agent": "Mozilla/5.0"})
            location = req_2.headers.get("Location", "")

            subtitle_url = self.fetch_best_subtitle_url(seed, language) if language else None

            if "vidsrc.stream" in location:
                stream_url = self.handle_vidsrc_stream(location, f"https://rcp.vidsrc.me/rcp/{source}")
                return stream_url, subtitle_url
            elif "2embed.cc" in location:
                print("[Advertencia] 2Embed no está implementado actualmente.")
                return self.handle_2embed(location, f"https://rcp.vidsrc.me/rcp/{source}"), subtitle_url
            elif "multiembed.mov" in location:
                stream_url = self.handle_multiembed(location, f"https://rcp.vidsrc.me/rcp/{source}")
                return stream_url, subtitle_url

            print("[Error] Location no contiene un proveedor conocido.")
            return None, subtitle_url

        except requests.RequestException as e:
            print(f"[Error] Fallo al solicitar stream: {e}")
            return None, None


if __name__ == "__main__":
    vse = VidSrcExtractor()
    code = input("Input TMDB code for the movie: ")
    stream, subtitle = vse.get_vidsrc_stream("multiembed", "movie", code, "eng")
    print(f"Stream: {stream}")
    print(f"Subtitle: {subtitle}")
