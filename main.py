import os
import json
from flask import Flask, request
import telebot
from google import genai
from google.genai import types
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image

# 1. Inicialización de Flask para Render
app = Flask(__name__)

# 2. Configuración Segura mediante Variables de Entorno (Environment Variables)
# Extraemos los tokens desde el sistema operativo para que no queden expuestos en el código
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL") # URL de tu servicio en Render

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 3. Configuración de Google Sheets con bloque PEM limpio
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client_sheets = gspread.authorize(creds)

SPREADSHEET_ID = "1Rd-I4-OAXPRQONbO9jyB_zai4PErAx34AvXvX0Dsoac"
sheet = client_sheets.open_by_key(SPREADSHEET_ID).sheet1

# Definición del esquema estructurado para Gemini con la nueva columna
class DatosLibro(types.BaseModel):
    titulo: str
    autor: str
    anio: str
    adicional: str

# 4. Endpoints para que Render reciba las notificaciones de Telegram
@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=RENDER_EXTERNAL_URL + '/' + TELEGRAM_TOKEN)
    return "Webhook configurado correctamente", 200

# 5. Manejador de imágenes en Telegram
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        # Si el usuario añade un texto junto con la foto (un caption), lo tomaremos como la instrucción adicional
        instruccion_usuario = message.caption if message.caption else "No se especificó ninguna instrucción adicional."
        
        bot.reply_to(message, "Procesando la portada con Gemini... Un momento, por favor.")
        
        # Descarga de la imagen enviada
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        image_path = "/tmp/temp_book.jpg" # Usamos la carpeta /tmp que es la permitida en servidores Linux como Render
        with open(image_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        # Carga de la imagen con PIL para enviarla inline a Gemini
        imagen_libro = Image.open(image_path)

        # Ajustamos el prompt dinámicamente según lo que el usuario escribió junto a la foto
        prompt = (
            f"Analiza la portada o página de créditos de este libro. Extrae el título del libro, "
            f"el nombre del autor principal y el año de publicación o edición (si no lo encuentras, coloca 'Desconocido').\n"
            f"Además, procesa la siguiente solicitud del usuario para llenar el campo 'adicional': {instruccion_usuario}. "
            f"Si la solicitud no pide extraer algo específico de la imagen, genera un resumen muy breve o nota relevante del libro "
            f"basándote en tus conocimientos."
        )

        # Generación de contenido estructurado
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[imagen_libro, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DatosLibro,
            ),
        )

        datos = json.loads(response.text)
        
        # Guardar en Google Sheets (Columnas: Título, Autor, Año, Adicional)
        sheet.append_row([datos['titulo'], datos['autor'], datos['anio'], datos['adicional']])
        
        # Respuesta elegante en Telegram
        respuesta_usuario = (
            f"✅ *¡Libro registrado en tu Sheets!*\n\n"
            f"📖 *Título:* {datos['titulo']}\n"
            f"✍️ *Autor:* {datos['autor']}\n"
            f"📅 *Año:* {datos['anio']}\n"
            f"💡 *Adicional:* {datos['adicional']}"
        )
        bot.reply_to(message, respuesta_usuario, parse_mode="Markdown")

        # Limpieza de archivos del servidor
        if os.path.exists(image_path):
            os.remove(image_path)

    except Exception as e:
        bot.reply_to(message, f"❌ Ocurrió un error al procesar el libro: {str(e)}")

if __name__ == "__main__":
    # Render asigna automáticamente un puerto dinámico a través de la variable de entorno PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
