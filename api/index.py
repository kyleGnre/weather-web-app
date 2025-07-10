from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timedelta
import requests
import json
import openai 

import os

def load_api_keys():
    secrets_file = os.path.join(os.path.dirname(__file__), "secrets.json")
    try:
        with open(secrets_file) as f:
            secrets = json.load(f)
        return secrets
    except Exception as e:
        print(f"Error loading secrets file: {e}")
        return None

api_keys = load_api_keys()

if api_keys is None:
    raise RuntimeError("Failed to load API keys from secrets.json")

try:
    openweather_api_key = api_keys['OPENWEATHER_API_KEY']
    openai.api_key = api_keys['OPENAI_API_KEY']
except KeyError as e:
    raise RuntimeError(f"Missing expected API key in secrets.json: {e}")

app = Flask(__name__)
CORS(app)

@app.route('/api/weather', methods=['POST'])
def send_location():
    data = request.get_json()
    user_location = data.get('userLocation', 'Houston')
    units = data.get('units', 'imperial')
    print("Received weather request:", data)

    # Build and call OpenWeather Current Weather API
    weather_URL = f'https://api.openweathermap.org/data/2.5/weather?q={user_location}&units={units}&appid={openweather_api_key}'
    weather_response = requests.get(weather_URL)

    if not weather_response.ok:
        print("Weather API failed:", weather_response.text)
        return jsonify({'error': 'Failed to retrieve weather data'}), 500

    weather_data = weather_response.json()
    city = weather_data.get("name", "N/A")
    temp = weather_data.get("main", {}).get("temp", "N/A")
    description = weather_data.get("weather", [{}])[0].get("description", "N/A")
    coords = weather_data.get("coord", {})
    temp_high = weather_data.get("main", {}).get("temp_max", "N/A")
    temp_low = weather_data.get("main", {}).get("temp_min", "N/A")
    feels_like = weather_data.get("main", {}).get("feels_like", "N/A")
    wind = weather_data.get("wind", {}).get("speed", "N/A")

    try:
        dt_utc = datetime.utcfromtimestamp(weather_data.get("dt", 0))
        timezone_offset = timedelta(seconds=weather_data.get("timezone", 0))
        local_time = dt_utc + timezone_offset
        local_time_iso = local_time.isoformat()
    except:
        local_time_iso = "N/A"

    # Initialize fallback values
    uv = "N/A"
    rain_percent = "N/A"
    hourly_data = []
    forecast_data = []

    # Use OneCall for forecast if coordinates are present
    if coords:
        lat, lon = coords.get("lat"), coords.get("lon")
        onecall_URL = f'https://api.openweathermap.org/data/2.5/onecall?lat={lat}&lon={lon}&exclude=minutely&units={units}&appid={openweather_api_key}'
        onecall_response = requests.get(onecall_URL)

        if onecall_response.ok:
            onecall_data = onecall_response.json()
            uv = onecall_data.get("current", {}).get("uvi", "N/A")
            rain_percent = onecall_data.get("hourly", [{}])[0].get("pop", 0) * 100

            # Hourly data
            for i in onecall_data.get('hourly', [])[:6]:
                hourly_temp = round(i.get('temp', 0))
                hourly_time = datetime.fromtimestamp(i['dt'] + weather_data.get("timezone", 0))
                hour = hourly_time.hour % 12 or 12
                am_pm = 'AM' if hourly_time.hour < 12 else 'PM'
                hourly_data.append({'temp': hourly_temp, 'time': f'{hour} {am_pm}'})

            # 7-Day Forecast
            forecast_data = process_forecast_data(onecall_data.get('daily', [])[:7])
        else:
            print("OneCall failed:", onecall_response.text)

    return jsonify({
        'city': city,
        'temp': temp,
        'description': description,
        'local_time': local_time_iso,
        'feels_like': feels_like,
        'wind': wind,
        'uv': uv,
        'rain_percent': rain_percent,
        'temp_high': temp_high,
        'temp_low': temp_low,
        'hourly_data': hourly_data,
        'forecast': forecast_data
    })

def process_forecast_data(daily_forecast):
    return [
        {
            'date': datetime.fromtimestamp(day['dt']).strftime('%Y-%m-%d'),
            'temp': day['temp']['day'],
            'rain_chance': day.get('pop', 0) * 100
        } for day in daily_forecast
    ]

@app.route('/api/chatgpt', methods=['POST'])
def chatgptResponse():
    try:
        input = request.get_json()
        print("Received data:", input)

        user_city = input.get('user_city', '').strip()
        if not user_city:
            return jsonify({'text': 'City name not provided.'}), 400

        messages = [{
            'role': 'user',
            'content': (
                f"What are some things to do in {user_city}? Please keep the response short (around 50 words or less). "
                "I want the answer to be in-line with this example: "
                "If the question is regarding Houston, I want the answer to be "
                "'In Houston, consider exploring Buffalo Bayou Park where you can take a stroll or bike ride along the scenic trails that wind through this 160-acre park', "
                "then any more supplemental details (DO NOT EXPLICITLY STATE THAT YOU ARE PROVIDING SUPPLEMENTAL DETAILS). "
                "KEEP THE RESPONSE SHORT! THIS IS GOING TO BE USED ON THE FRONT PAGE OF A WEATHER APP. "
                "DO NOT MENTION THE SAME SUGGESTION MORE THAN ONCE, ALWAYS PICK SOMETHING NEW FROM THE AREA."
            )
        }]

        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        answer = completion['choices'][0]['message']['content'].strip()
        print("GPT response:", answer)
        return jsonify({'text': answer})

    except Exception as e:
        print("Error in /api/chatgpt:", str(e))
        return jsonify({'text': 'Internal server error occurred.'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5328, debug=True)
