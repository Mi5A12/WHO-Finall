import os
import json
import logging
from flask import Flask, request, render_template, jsonify, url_for
import requests
from bs4 import BeautifulSoup
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from google.cloud import storage
from flask import session
from flask_session import Session
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "fallback-secret-key")
app.config["SESSION_TYPE"] = "filesystem"  # Store session data on the server

Session(app)  # Initialize Flask session management

# Configure logging
logging.basicConfig(level=logging.INFO)



BITRIX_CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
BITRIX_CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")
BITRIX_REDIRECT_URI = "https://who-finall.onrender.com/oauth"
BITRIX_AUTH_URL = "https://cultiv.bitrix24.com/oauth/authorize/"
BITRIX_TOKEN_URL = "https://cultiv.bitrix24.com/oauth/token/"
BITRIX_API_URL = "https://cultiv.bitrix24.com/rest/"

def get_bitrix_token(code):
    """Exchange the authorization code for an access token from Bitrix24."""
    try:
        payload = {
            "grant_type": "authorization_code",
            "client_id": BITRIX_CLIENT_ID,
            "client_secret": BITRIX_CLIENT_SECRET,
            "redirect_uri": BITRIX_REDIRECT_URI,
            "code": code,
        }
        response = requests.post(BITRIX_TOKEN_URL, data=payload)
        token_data = response.json()

        if "access_token" in token_data:
            logging.info("Bitrix24 Access Token received successfully.")
            return token_data
        else:
            logging.error(f"Failed to retrieve Bitrix24 access token: {token_data}")
            return None
    except Exception as e:
        logging.error(f"Error in get_bitrix_token(): {e}")
        return None

def refresh_bitrix_token():
    """Refresh Bitrix24 OAuth Token."""
    try:
        if "refresh_token" not in session:
            logging.error("No refresh token found in session.")
            return None
        
        payload = {
            "grant_type": "refresh_token",
            "client_id": BITRIX_CLIENT_ID,
            "client_secret": BITRIX_CLIENT_SECRET,
            "refresh_token": session.get("refresh_token"),
        }

        response = requests.post(BITRIX_TOKEN_URL, data=payload)
        token_data = response.json()

        if "access_token" in token_data:
            session["access_token"] = token_data["access_token"]
            session["refresh_token"] = token_data["refresh_token"]
            logging.info("Bitrix24 OAuth token refreshed successfully.")
            return token_data["access_token"]
        else:
            logging.error(f"Failed to refresh Bitrix24 token: {token_data}")
            return None

    except Exception as e:
        logging.error(f"Token refresh error: {e}")
        return None
    
# Configuration
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static/charts')
DOWNLOAD_FOLDER = os.getenv('DOWNLOAD_FOLDER', 'downloads')
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'child-growth-charts')

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

@app.route('/oauth')
def oauth():
    """Handle OAuth callback from Bitrix24."""
    code = request.args.get('code')

    if not code:
        return jsonify({"error": "Authorization code not provided"}), 400

    token_data = get_bitrix_token(code)

    if not token_data or "access_token" not in token_data:
        return jsonify({"error": "Failed to retrieve access token"}), 400

    # Store the access token in session
    session['access_token'] = token_data["access_token"]
    session['refresh_token'] = token_data["refresh_token"]

    return jsonify({"message": "Bitrix24 Authentication Successful!"})

# Google Cloud Storage client
storage_client = storage.Client()

def upload_to_gcs(file_path, destination_blob_name):
    try:
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(destination_blob_name)

        if not os.path.isfile(file_path):
            logging.error(f"File not found: {file_path}")
            return None

        blob.upload_from_filename(file_path)
        return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{destination_blob_name}"

    except Exception as e:
        logging.error(f"Error uploading to GCS: {e}")
        return None

def normalize_columns(dataframe):
    column_mapping = {
        "Year: Month": "Age (years)",
        "Month": "Age (months)",
        "3rd": "3rd Percentile",
        "15th": "15th Percentile",
        "50th": "50th Percentile",
        "85th": "85th Percentile",
        "97th": "97th Percentile",
        "-3 SD": "-3SD Z-Scores",
        "-2 SD": "-2SD Z-Scores",
        "-1 SD": "-1SD Z-Scores",
        "Median": "Median Z-Scores",
        "1 SD": "1SD Z-Scores",
        "2 SD": "2SD Z-Scores",
        "3 SD": "3SD Z-Scores",
        "3rdd": "3rd Z-Scores",
        "15thh": "15th Z-Scores",
        "Mediann": "Median Z Scores",
        "85thh": "85th Z-Scores",
        "97thh": "97th Z-Scores",
    }
    dataframe.rename(columns=column_mapping, inplace=True)
    if "Age (years)" in dataframe.columns:
        dataframe["Age (years)"] = dataframe["Age (years)"].apply(parse_age)
    return dataframe

def parse_age(year_month):
    try:
        years, months = map(int, year_month.split(":"))
        return years + (months / 12)
    except ValueError:
        return None

def load_reference_data():
    csv_files = {
        "bmifa_boys_per": "csv_files/bmifa-boys-5-19years-per.csv",
        "bmifa_boys_z": "csv_files/bmifa-boys-5-19years-z.csv",
        "bmifa_girls_per": "csv_files/bmifa-girls-5-19years-per.csv",
        "bmifa_girls_z": "csv_files/bmifa-girls-5-19years-z.csv",
        "hfa_boys_per": "csv_files/hfa-boys-5-19years-per.csv",
        "hfa_boys_z": "csv_files/sft-hfa-boys-perc-5-19years.csv",
        "hfa_girls_per": "csv_files/hfa-girls-5-19years-per.csv",
        "hfa_girls_z": "csv_files/sft-hfa-girls-perc-5-19years.csv",
        "wfa_boys_per": "csv_files/wfa-boys-5-10years-per.csv",
        "wfa_boys_z": "csv_files/wfa-boys-5-10years-z.csv",
        "wfa_girls_per": "csv_files/wfa-girls-5-10years-per.csv",
        "wfa_girls_z": "csv_files/wfa-girls-5-10years-z.csv",
    }
    data = {}
    for key, file_path in csv_files.items():
        try:
            df = pd.read_csv(file_path)
            df = normalize_columns(df)
            data[key] = df
        except Exception as e:
            logging.error(f"Error loading {file_path}: {e}")
    return data

reference_data = load_reference_data()

def extract_data_from_url(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        data_texts = soup.find_all("div", {"class": "data-text font-size-nom bold"})
        box_texts = soup.find_all("div", {"class": "box"})
        td_center_spans = soup.find_all("div", {"class": "td t-center", "style": "width:55%; text-align: right;"})

        data = {
            "name": soup.find("span", {"class": "name abs"}).text.strip() if soup.find("span", {"class": "name abs"}) else "Unknown",
            "age": soup.find("span", {"class": "old abs"}).text.strip() if soup.find("span", {"class": "old abs"}) else "0",
            "gender": soup.find("span", {"class": "sex abs"}).text.strip() if soup.find("span", {"class": "sex abs"}) else "Unknown",
            "height": soup.find("span", {"class": "height abs"}).text.strip() if soup.find("span", {"class": "height abs"}) else "0 cm",
            "weight": data_texts[0].text.strip() if len(data_texts) > 0 else "0",
            "smm": data_texts[1].text.strip() if len(data_texts) > 1 else "0",
            "bmi": data_texts[3].text.strip() if len(data_texts) > 3 else "0",
            "pbf": data_texts[4].text.strip() if len(data_texts) > 4 else "0",
            "score": box_texts[0].text.strip() if len(box_texts) > 0 else "0",
            "ecf": soup.find_all("div", {"class": "bold"})[1].text.strip(),
            "cf": soup.find_all("div", {"class": "bold"})[2].text.strip(),
            "protein": soup.find_all("div", {"class": "bold"})[3].text.strip(),
            "minerals": soup.find_all("div", {"class": "bold"})[4].text.strip(),
            "fat": soup.find_all("div", {"class": "bold"})[5].text.strip(),
            "body_water": soup.find_all("div", {"class": "bold"})[6].text.strip(),
            "soft_lean_mass": soup.find_all("div", {"class": "bold"})[7].text.strip(),
            "fat_free_mass": soup.find_all("div", {"class": "bold"})[8].text.strip(),
            "body_fat_mass": data_texts[2].text.strip() if len(data_texts) > 2 else "0",
            "basal_metabolic_rate": td_center_spans[0].find("span").text.strip() if len(td_center_spans) > 0 else "0",
            "bone_mineral": td_center_spans[1].find("span").text.strip() if len(td_center_spans) > 1 else "0",
            "waist_hip_ratio": td_center_spans[2].find("span").text.strip() if len(td_center_spans) > 2 else "0",
            "visceral_fat_level": td_center_spans[3].find("span").text.strip() if len(td_center_spans) > 3 else "0",
        }
        return data
    except requests.exceptions.RequestException as e:
        logging.error(f"Error extracting data from URL: {e}")
        return None

def plot_growth_chart(data, age, metric, metric_label, title, output_path):
    try:
        plt.figure(figsize=(6, 8))
        for col in ["3rd Percentile", "15th Percentile", "50th Percentile", "85th Percentile", "97th Percentile", 
                    "-3SD Z-Scores", "-2SD Z-Scores", "-1SD Z-Scores", "Median Z-Scores", 
                    "1SD Z-Scores", "2SD Z-Scores", "3SD Z-Scores", "3rd Z-Scores", 
                    "15th Z-Scores", "Median Z Scores", "85th Z-Scores", "97th Z-Scores"]:
            if col in data.columns:
                plt.plot(data["Age (years)"], data[col], label=col)

        plt.scatter([age], [metric], color="red", label="Child's Data", zorder=5)
        plt.title(title)
        plt.xlabel("Age (years)")
        plt.ylabel(metric_label)
        plt.legend()
        plt.grid(True)
        plt.savefig(output_path)
        plt.close()
    except Exception as e:
        logging.error(f"Error in plot_growth_chart: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    """Main page for embedding inside Bitrix24."""
    logging.info(f"Received {request.method} request at / with headers: {dict(request.headers)}")

    # ✅ Instead of JSON, always return the UI
    return render_template('index.html', BITRIX_CLIENT_ID=BITRIX_CLIENT_ID)

@app.route('/process', methods=['POST'])
def process():
    link = request.form.get('link')
    rpa_id = request.form.get('rpa_id')

    if not link or not rpa_id:
        return render_template('index.html', error="Please provide both a valid link and RPA ID.")

    try:
        extracted_data = extract_data_from_url(link)
        if not extracted_data:
            return render_template('index.html', error="Failed to extract data from the provided link.")

        age = int(extracted_data['age'])
        height = float(extracted_data['height'].replace("cm", ""))
        weight = float(extracted_data['weight'])
        bmi = float(extracted_data['bmi'])

        gender_key = 'boys' if extracted_data['gender'].lower() == 'male' else 'girls'

        chart_paths = {
            "bmi_chart_per": os.path.join(UPLOAD_FOLDER, "bmi_chart_per.png"),
            "bmi_chart_z": os.path.join(UPLOAD_FOLDER, "bmi_chart_z.png"),
            "height_chart_per": os.path.join(UPLOAD_FOLDER, "height_chart_per.png"),
            "height_chart_z": os.path.join(UPLOAD_FOLDER, "height_chart_z.png"),
            "weight_chart_per": os.path.join(UPLOAD_FOLDER, "weight_chart_per.png"),
            "weight_chart_z": os.path.join(UPLOAD_FOLDER, "weight_chart_z.png")
        }

        plot_growth_chart(reference_data.get(f'bmifa_{gender_key}_per', pd.DataFrame()), age, bmi, "BMI", "BMI Chart", chart_paths["bmi_chart_per"])
        plot_growth_chart(reference_data.get(f'bmifa_{gender_key}_z', pd.DataFrame()), age, bmi, "BMI Z-Score", "BMI Z-Score Chart", chart_paths["bmi_chart_z"])
        plot_growth_chart(reference_data.get(f'hfa_{gender_key}_per', pd.DataFrame()), age, height, "Height (cm)", "Height Chart", chart_paths["height_chart_per"])
        plot_growth_chart(reference_data.get(f'hfa_{gender_key}_z', pd.DataFrame()), age, height, "Height Z-Score", "Height Z-Score Chart", chart_paths["height_chart_z"])
        plot_growth_chart(reference_data.get(f'wfa_{gender_key}_per', pd.DataFrame()), age, weight, "Weight (kg)", "Weight Chart", chart_paths["weight_chart_per"])
        plot_growth_chart(reference_data.get(f'wfa_{gender_key}_z', pd.DataFrame()), age, weight, "Weight Z-Score", "Weight Z-Score Chart", chart_paths["weight_chart_z"])

        gcs_links = {}
        for key, path in chart_paths.items():
            name_clean = extracted_data['name'].replace(" ", "_")
            gcs_link = upload_to_gcs(path, f"{name_clean}_{key}.png")
            if gcs_link:
                logging.info(f"Uploaded {key}: {gcs_link}")
            else:
                logging.error(f"Failed to upload {key}")
            gcs_links[key] = gcs_link

        query_params = {
            "typeId": 1,
            "id": rpa_id,
            "fields[UF_RPA_1_WEIGHT]": weight,
            "fields[UF_RPA_1_HEIGHT]": height,
            "fields[UF_RPA_1_1734279376]": bmi,
            "fields[UF_RPA_1_1734278050]": age,
            "fields[UF_RPA_1_1733491182]": link,
            "fields[UF_RPA_1_1738508202]": extracted_data.get("gender"),
            "fields[UF_RPA_1_1738508402]": gcs_links.get("bmi_chart_per"),
            "fields[UF_RPA_1_1738508416]": gcs_links.get("bmi_chart_z"),
            "fields[UF_RPA_1_1738508425]": gcs_links.get("height_chart_per"),
            "fields[UF_RPA_1_1738508434]": gcs_links.get("height_chart_z"),
            "fields[UF_RPA_1_1738508444]": gcs_links.get("weight_chart_per"),
            "fields[UF_RPA_1_1738508458]": gcs_links.get("weight_chart_z"),
            "fields[UF_RPA_1_1738508088]": extracted_data.get("score"),
            "fields[UF_RPA_1_1738508230]": extracted_data.get("ecf"),
            "fields[UF_RPA_1_1738508241]": extracted_data.get("cf"),
            "fields[UF_RPA_1_1738508249]": extracted_data.get("protein"),
            "fields[UF_RPA_1_1738508256]": extracted_data.get("minerals"),
            "fields[UF_RPA_1_1738508263]": extracted_data.get("fat"),
            "fields[UF_RPA_1_1738508271]": extracted_data.get("body_water"),
            "fields[UF_RPA_1_1738508280]": extracted_data.get("soft_lean_mass"),
            "fields[UF_RPA_1_1738508290]": extracted_data.get("fat_free_mass"),
            "fields[UF_RPA_1_1738508302]": extracted_data.get("smm"),
            "fields[UF_RPA_1_1738508319]": extracted_data.get("body_fat_mass"),
            "fields[UF_RPA_1_1738508352]": extracted_data.get("basal_metabolic_rate"),
            "fields[UF_RPA_1_1738508366]": extracted_data.get("bone_mineral"),
            "fields[UF_RPA_1_1738508379]": extracted_data.get("waist_hip_ratio"),
            "fields[UF_RPA_1_1738508390]": extracted_data.get("visceral_fat_level"),
            "fields[UF_RPA_1_1738508329]": extracted_data.get("pbf")
        }

        target_url = "https://vitrah.bitrix24.com/rest/1/15urrpzalz7xkysu/rpa.item.update.json"
        response = requests.post(target_url, data=query_params)
        response.raise_for_status()

        return render_template('index.html', success="Data sent successfully to Bitrix24!")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send data: {e.response.text if e.response else str(e)}")
        return render_template('index.html', error=f"Failed to send data: {e.response.text if e.response else str(e)}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return render_template('index.html', error=f"An unexpected error occurred: {str(e)}")

@app.route('/test_bitrix', methods=['GET'])
def test_bitrix():
    """Test if the access token is working by fetching current user info from Bitrix24."""
    if "access_token" not in session:
        logging.warning("Access token not found, attempting refresh...")
        new_token = refresh_bitrix_token()
        if not new_token:
            return jsonify({"error": "User not authenticated with Bitrix24"}), 401

    access_token = session["access_token"]
    url = f"https://cultiv.bitrix24.com/rest/user.current.json"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(url, headers=headers)

    # If access token is expired, refresh it
    if response.status_code == 401:
        logging.warning("Access token expired. Attempting to refresh...")
        new_token = refresh_bitrix_token()
        if not new_token:
            return jsonify({"error": "Failed to refresh token"}), 401
        headers["Authorization"] = f"Bearer {new_token}"
        response = requests.get(url, headers=headers)  # Retry request

    return response.json()

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Handle incoming requests from Bitrix24 and update the RPA record."""
    try:
        # Ensure the user is authenticated with Bitrix24
        if "access_token" not in session:
            return jsonify({"status": "error", "message": "User not authenticated with Bitrix24"}), 401

        # Extract parameters from request
        link = request.args.get('link') or request.form.get('link')
        rpa_id = request.args.get('rpa_id') or request.form.get('rpa_id')

        if not link or not rpa_id:
            return jsonify({"status": "error", "message": "Missing required parameters: link and rpa_id"}), 400

        # Extract child growth data
        extracted_data = extract_data_from_url(link)
        if not extracted_data:
            return jsonify({"status": "error", "message": "Failed to extract data from the provided link"}), 400

        age = int(extracted_data.get('age', 0))
        height = float(extracted_data.get('height', '0').replace("cm", ""))
        weight = float(extracted_data.get('weight', '0'))
        bmi = float(extracted_data.get('bmi', '0'))
        gender_key = 'boys' if extracted_data.get('gender', '').lower() == 'male' else 'girls'

        # Generate growth charts
        chart_paths = {
            "bmi_chart_per": os.path.join(UPLOAD_FOLDER, "bmi_chart_per.png"),
            "bmi_chart_z": os.path.join(UPLOAD_FOLDER, "bmi_chart_z.png"),
            "height_chart_per": os.path.join(UPLOAD_FOLDER, "height_chart_per.png"),
            "height_chart_z": os.path.join(UPLOAD_FOLDER, "height_chart_z.png"),
            "weight_chart_per": os.path.join(UPLOAD_FOLDER, "weight_chart_per.png"),
            "weight_chart_z": os.path.join(UPLOAD_FOLDER, "weight_chart_z.png")
        }

        plot_growth_chart(reference_data.get(f'bmifa_{gender_key}_per', pd.DataFrame()), age, bmi, "BMI", "BMI Chart", chart_paths["bmi_chart_per"])
        plot_growth_chart(reference_data.get(f'bmifa_{gender_key}_z', pd.DataFrame()), age, bmi, "BMI Z-Score", "BMI Z-Score Chart", chart_paths["bmi_chart_z"])
        plot_growth_chart(reference_data.get(f'hfa_{gender_key}_per', pd.DataFrame()), age, height, "Height (cm)", "Height Chart", chart_paths["height_chart_per"])
        plot_growth_chart(reference_data.get(f'hfa_{gender_key}_z', pd.DataFrame()), age, height, "Height Z-Score", "Height Z-Score Chart", chart_paths["height_chart_z"])
        plot_growth_chart(reference_data.get(f'wfa_{gender_key}_per', pd.DataFrame()), age, weight, "Weight (kg)", "Weight Chart", chart_paths["weight_chart_per"])
        plot_growth_chart(reference_data.get(f'wfa_{gender_key}_z', pd.DataFrame()), age, weight, "Weight Z-Score", "Weight Z-Score Chart", chart_paths["weight_chart_z"])

        # Upload charts to Google Cloud Storage
        gcs_links = {}
        for key, path in chart_paths.items():
            name_clean = extracted_data['name'].replace(" ", "_")
            gcs_link = upload_to_gcs(path, f"{name_clean}_{key}.png")
            if gcs_link:
                logging.info(f"Uploaded {key}: {gcs_link}")
            else:
                logging.error(f"Failed to upload {key}")
            gcs_links[key] = gcs_link

        # Prepare API request payload
        query_params = {
            "id": rpa_id,
            "fields": {
                "UF_RPA_1_WEIGHT": weight,
                "UF_RPA_1_HEIGHT": height,
                "UF_RPA_1_1734279376": bmi,
                "UF_RPA_1_1734278050": age,
                "UF_RPA_1_1733491182": link,
                "UF_RPA_1_1738508202": extracted_data.get("gender"),
                "UF_RPA_1_1738508402": gcs_links.get("bmi_chart_per"),
                "UF_RPA_1_1738508416": gcs_links.get("bmi_chart_z"),
                "UF_RPA_1_1738508425": gcs_links.get("height_chart_per"),
                "UF_RPA_1_1738508434": gcs_links.get("height_chart_z"),
                "UF_RPA_1_1738508444": gcs_links.get("weight_chart_per"),
                "UF_RPA_1_1738508458": gcs_links.get("weight_chart_z"),
                "UF_RPA_1_1738508088": extracted_data.get("score"),
                "UF_RPA_1_1738508230": extracted_data.get("ecf"),
                "UF_RPA_1_1738508241": extracted_data.get("cf"),
                "UF_RPA_1_1738508249": extracted_data.get("protein"),
                "UF_RPA_1_1738508256": extracted_data.get("minerals"),
                "UF_RPA_1_1738508263": extracted_data.get("fat"),
                "UF_RPA_1_1738508271": extracted_data.get("body_water"),
                "UF_RPA_1_1738508280": extracted_data.get("soft_lean_mass"),
                "UF_RPA_1_1738508290": extracted_data.get("fat_free_mass"),
                "UF_RPA_1_1738508302": extracted_data.get("smm"),
                "UF_RPA_1_1738508319": extracted_data.get("body_fat_mass"),
                "UF_RPA_1_1738508352": extracted_data.get("basal_metabolic_rate"),
                "UF_RPA_1_1738508366": extracted_data.get("bone_mineral"),
                "UF_RPA_1_1738508379": extracted_data.get("waist_hip_ratio"),
                "UF_RPA_1_1738508390": extracted_data.get("visceral_fat_level"),
                "UF_RPA_1_1738508329": extracted_data.get("pbf"),
            }
        }

        # Send request to Bitrix24 using OAuth token
        target_url = f"{BITRIX_API_URL}rpa.item.update.json"
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        response = requests.post(target_url, json=query_params, headers=headers)

        if response.status_code == 200:
            return jsonify({"status": "success", "message": "Data sent successfully to Bitrix24!"}), 200
        else:
            logging.error(f"Bitrix24 API Error: {response.text}")
            return jsonify({"status": "error", "message": "Failed to send data", "details": response.text}), 500

    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send data: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to send data: {str(e)}"}), 500

    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        return jsonify({"status": "error", "message": f"An unexpected error occurred: {str(e)}"}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5002)
