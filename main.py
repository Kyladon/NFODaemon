# SPRE NFO Daemon
# v1.6

import os
import base64
import hashlib
import threading
import time
from flask import Flask, request, send_file, send_from_directory, render_template_string, jsonify, url_for
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from datetime import datetime

app = Flask(__name__)

# make sure static and fonts directories exist
os.makedirs('static', exist_ok=True)
os.makedirs('fonts', exist_ok=True)

#----------------------------------------------------------------------------------------------------
#-VARIABLES-
#-Server settings
timeout_seconds = 300                  # NFO timeout, how long before the files are deleted. 300=5mins
server_port = 6789                     # Set the server port
debug_mode = False                      # Debug Mode, dont forget to disable this once you are happy it works!
host_ip = '0.0.0.0'                    # Set the host IP interface. 0.0.0.0 for all

#-NFO Render settings
font_path = "fonts/cp437_IBM_VGA8.ttf" # Font to render NFOs. I find this is the best one to get a decent clean render
font_size = 16                         # 16 is the perfect size to render cp437_IBM_VGA8.
font_color = "white"                   # Font colour to render
background_color = "black"             # Background colour to render. Note, you should also adjust the HTML color scheme if you change this

TOKEN_FILE = 'tokens.txt'              # Access tokens for REST API Access

#-Lets Encrypt certificates (make sure these are accessible by the daemon user)
le_fullchain = "fullchain.pem"         # SSL fullchain pem
le_privkey = "privkey.pem"             # SSL privkey pem
#----------------------------------------------------------------------------------------------------

VALID_TOKENS = set()

def load_tokens():
    global VALID_TOKENS
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as file:
            VALID_TOKENS = set(line.strip() for line in file)

def token_required(f):
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or token not in VALID_TOKENS:
            return jsonify({"message": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

load_tokens()

def read_nfo_from_base64(base64_data):
    decoded_data = base64.b64decode(base64_data).decode('cp437')
    return decoded_data.splitlines()

def render_nfo_to_image(lines):
    font = ImageFont.truetype(font_path, font_size)
    
    # Time to calculate the size of the image
    padding = 20
    max_text_width = max(font.getbbox(line)[2] for line in lines)
    width = max_text_width + padding * 2
    height = len(lines) * font_size + padding * 2
    
    image = Image.new('RGB', (int(width), height), color=background_color)
    draw = ImageDraw.Draw(image)
    
    # Render the NFO text
    y = padding
    for line in lines:
        draw.text((padding, y), line.strip('\r\n'), font=font, fill=font_color)
        y += font_size

    return image

def save_sfv_files(sfvs, hexdig):
    saved_paths = []
    for i, sfv in enumerate(sfvs):
        sfv_data = sfv['sfv_data']
        sfvname = sfv['sfvname']
        sfvpath = sfv.get('sfvpath', '')

        sfv_lines = read_nfo_from_base64(sfv_data)
        sfv_image = render_nfo_to_image(sfv_lines)

        sfv_hash_input = sfv_data + datetime.now().strftime("%Y%m%d%H%M%S%f")
        sfv_hash_object = hashlib.md5(sfv_hash_input.encode())
        sfv_hexdig = sfv_hash_object.hexdigest()

        sfv_image_path = f"static/{sfv_hexdig}.png"
        sfv_image.save(sfv_image_path)

        sfv_data_path = f"static/{sfv_hexdig}.sfv"
        with open(sfv_data_path, 'wb') as f:
            f.write(base64.b64decode(sfv_data))
        
        saved_paths.append({
            'sfv_data_path': sfv_data_path,
            'sfv_image_path': sfv_image_path,
            'sfvname': sfvname,
            'sfvpath': sfvpath,
            'sfv_hexdig': sfv_hexdig
        })
    
    # Save the SFV metadata to a file for later retrieval
    sfv_metadata_path = f"static/{hexdig}_sfv_metadata.txt"
    with open(sfv_metadata_path, 'w') as f:
        for sfv in saved_paths:
            f.write(f"{sfv['sfv_hexdig']}|{sfv['sfvname']}|{sfv['sfvpath']}\n")
    
    return saved_paths

def load_sfv_metadata(hexdig):
    sfv_metadata_path = f"static/{hexdig}_sfv_metadata.txt"
    saved_paths = []
    if os.path.exists(sfv_metadata_path):
        with open(sfv_metadata_path, 'r') as f:
            for line in f:
                sfv_hexdig, sfvname, sfvpath = line.strip().split('|')
                sfv_data_path = f"static/{sfv_hexdig}.sfv"
                sfv_image_path = f"static/{sfv_hexdig}.png"
                saved_paths.append({
                    'sfv_data_path': sfv_data_path,
                    'sfv_image_path': sfv_image_path,
                    'sfvname': sfvname,
                    'sfvpath': sfvpath,
                    'sfv_hexdig': sfv_hexdig
                })
    return saved_paths

#----------------------
#-API Stuff
@app.route('/upload_nfo', methods=['POST'])
@token_required
def upload_nfo():
    required_fields = ['nfo_data', 'release', 'filename', 'save']
    data = request.json

    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return jsonify({"url": None, "message": f"Missing fields: {', '.join(missing_fields)}"}), 400

    try:
        base64_data = data['nfo_data']
        release = data['release']
        filename = data['filename']
        save = data['save']
        date = data.get('date', '')
        files = data.get('files', '')
        size = data.get('size', '')
        sfvs = data.get('sfvs', [])

        lines = read_nfo_from_base64(base64_data)
        image = render_nfo_to_image(lines)
       
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        
# create a unique hash for our files
        current_time = datetime.now().strftime("%Y%m%d%H%M%S%f")
        hash_input = base64_data + current_time
        hash_object = hashlib.md5(hash_input.encode())
        hexdig = hash_object.hexdigest()
        image_path = f"static/{hexdig}.png"
        image.save(image_path)
        
# Save the release information to a file
        release_info_path = f"static/{hexdig}.txt"
        with open(release_info_path, 'w') as f:
            f.write(release)
        
# Save the filename
        filename_info_path = f"static/{hexdig}_filename.txt"
        with open(filename_info_path, 'w') as f:
            f.write(filename)
        
# Save the NFO data if save is allowed
        if save:
            nfo_data_path = f"static/{hexdig}.nfo"
            with open(nfo_data_path, 'wb') as f:
                f.write(base64.b64decode(base64_data))
        else:
            nfo_data_path = None
        
        # Save optional data
        optional_fields_path = f"static/{hexdig}_optional.txt"
        with open(optional_fields_path, 'w') as f:
            f.write(f"{date}\n{files}\n{size}")
        
        # Save SFV files if provided
        saved_sfv_paths = []
        if sfvs:
            saved_sfv_paths = save_sfv_files(sfvs, hexdig)

        # Server the web page!
        threading.Thread(target=remove_file_after_delay, args=(image_path, release_info_path, nfo_data_path, filename_info_path, saved_sfv_paths, timeout_seconds)).start() 
        
        return jsonify({"url": f"/viewer/{hexdig}", "message": "Success"})
        
    except Exception as e:
        return jsonify({"url": None, "message": "Error"}), 500

@app.route('/viewer/<filename>')
def serve_image(filename):
    image_path = f"static/{filename}.png"
    release_info_path = f"static/{filename}.txt"
    filename_info_path = f"static/{filename}_filename.txt"
    optional_fields_path = f"static/{filename}_optional.txt"
    nfo_data_path = f"static/{filename}.nfo"
    
    if not os.path.exists(image_path) or not os.path.exists(release_info_path) or not os.path.exists(filename_info_path):
        return render_template_string('''
            <!doctype html>
            <html lang="en">
              <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
                <title>Hash not found</title>
                <link rel="stylesheet" href="{{ url_for('serve_fonts', filename='roboto.css') }}">
                <style>
                    body {
                        background-color: #1a1a1a;  /* Dark grey background */
                        color: white;
                        display: flex;
                        justify-content: center;
                        align-items: flex-start;
                        height: 100vh;
                        margin: 0;
                        font-family: 'Roboto', sans-serif;
                    }
                    .error-container {
                        background-color: black;
                        color: white;
                        border-radius: 15px;
                        padding: 10px 20px;
                        text-align: center;
                        margin-top: 20px;
                    }
                </style>
              </head>
              <body>
                <div class="error-container">
                    <h1>Hash not found</h1>
                </div>
              </body>
            </html>
        '''), 404
    
    with open(release_info_path, 'r') as f:
        release = f.read()

    with open(filename_info_path, 'r') as f:
        original_filename = f.read()
    
    date, files, size = '', '', ''
    if os.path.exists(optional_fields_path):
        with open(optional_fields_path, 'r') as f:
            optional_fields = f.read().splitlines()
            if len(optional_fields) > 0:
                date = optional_fields[0]
            if len(optional_fields) > 1:
                files = optional_fields[1]
            if len(optional_fields) > 2:
                size = f"{optional_fields[2]} MB" if optional_fields[2] else ""
    
    if os.path.exists(nfo_data_path):
        download_button = f'<hr><div style="text-align: center;"><a href="/download/{filename}" class="download-button">Download NFO</a></div>'
        expired_message = '<div id="expired-banner" class="expired-banner" style="display:none; font-weight:bold; color:red; text-align: center;">Hash has expired</div>'
        
    else:
        download_button = ''
        expired_message = '<div id="expired-banner" class="expired-banner" style="display:none; font-weight:bold; color:red; text-align: center;">Hash has expired</div>'

    max_label_length = max(len(label) for label in ["File Name", "Pre Date", "Files", "Size"])
    max_value_length = max(len(value) for value in [original_filename, date, files, size])
    col_width = max(max_label_length, max_value_length) + 2  # Adding padding

    # Load SFV metadata for display
    saved_sfv_paths = load_sfv_metadata(filename)
    sfv_renderings = ''
    for sfv in saved_sfv_paths:
        sfv_filename = sfv['sfvname']
        sfv_image_path = sfv['sfv_image_path']
        sfv_path = sfv['sfvpath']
        sfv_hexdig = sfv['sfv_hexdig']

        # Create SFV table HTML
        sfv_table = f'''
        <div class="info-table-container">
            <table class="info-table">
                <tr>
                    <th>SFV Filename</th>
                    <td>{sfv_filename}</td>
                </tr>
        '''
        if sfv_path:
            sfv_table += f'''
                <tr>
                    <th>SFV Path</th>
                    <td>{sfv_path}</td>
                </tr>
            '''
        sfv_table += f'''
            </table>
        </div>
        <p></p>
        <div style="text-align: center;"><a href="/download_sfv/{sfv_hexdig}" class="download-button">Download SFV</a></div>        
        <p></p>
        '''

        sfv_renderings += f'''
        <hr>
        {sfv_table}
        <table style="margin: 0 auto;">
            <tr>
                <td><img id="sfvImage" src="/static/{sfv_hexdig}.png" alt="SFV Image"></td>
            </tr>
        </table>
        '''

    html_content = f'''
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
            <title>{release}</title>
            <link rel="stylesheet" href="{{{{ url_for('serve_fonts', filename='roboto.css') }}}}">
            <style>
                body {{
                    background-color: #1a1a1a;  /* Dark grey background */
                    color: white;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    font-family: 'Roboto', sans-serif;
                    transition: all 0.5s ease;
                }}
                .title-container {{
                    background-color: black;
                    border-radius: 15px;
                    padding: 10px 20px;
                    margin-top: 20px;
                    text-align: center;
                }}
                h4 {{
                    margin: 0;
                }}
                .info-table-container {{
                    display: flex;
                    justify-content: center;
                    width: 100%;
                }}
                .info-table {{
                    width: auto;
                    margin-top: 20px;
                    border-collapse: collapse;
                }}
                .info-table td, .info-table th {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    width: {col_width}ch;
                }}
                .info-table th {{
                    background-color: #333;
                    color: white;
                    text-align: right;
                }}
                .info-table td {{
                    text-align: left;
                }}
                hr {{
                    border: 1px solid white;
                    width: 100%;
                    margin: 10px 0;
                }}
                table {{
                    margin-top: 20px;
                    border: 0;
                    background-color: black;  /* Black table background */
                    overflow: hidden;
                }}
                img {{
                    display: block;
                    transition: all 0.5s ease;
                }}
                .inverted {{
                    filter: invert(100%);
                    background-color: #f0f0f0;  /* Light grey background for contrast */
                }}
                .dropdown {{
                    position: absolute;
                    top: 10px;
                    right: 10px;
                }}
                select {{
                    font-family: 'Roboto', sans-serif;
                    padding: 5px 10px;
                    border-radius: 15px;  /* Rounded edges */
                    border: 1px solid #ccc;
                    background-color: white;
                    color: black;
                    transition: background-color 0.5s, color 0.5s;
                }}
                select:focus {{
                    outline: none;
                    border-color: #888;
                }}
                .download-button {{
                    display: block;
                    padding: 10px 20px;
                    border-radius: 15px;
                    background-color: white;
                    color: black;
                    text-decoration: none;
                    font-family: 'Roboto', sans-serif.
                }}
                .download-button:hover {{
                    background-color: #ccc;
                }}
                .expired-banner {{
                    margin-top: 10px;
                }}
            </style>
          </head>
          <body>
            <div class="dropdown">
                <select id="colorMode" onchange="toggleInvert()">
                    <option value="normal">Normal</option>
                    <option value="inverted">Blind Me</option>
                </select>
            </div>
            <div id="content">
                <div class="title-container">
                    <h4>{release}</h4>
                </div>
                <div class="info-table-container">
                    <table class="info-table">
                        <tr>
                            <th>File Name</th>
                            <td>{original_filename}</td>
                        </tr>
        '''
    if date:
        html_content += f'''
                        <tr>
                            <th>Pre Date</th>
                            <td>{date}</td>
                        </tr>
        '''
    if files:
        html_content += f'''
                        <tr>
                            <th>Files</th>
                            <td>{files}</td>
                        </tr>
        '''
    if size:
        html_content += f'''
                        <tr>
                            <th>Size</th>
                            <td>{size}</td>
                        </tr>
        '''
    html_content += f'''
                    </table>
                </div>
                {download_button}
                {expired_message}
                <table>
                  <tr>
                    <td><img id="nfoImage" src="/static/{filename}.png" alt="NFO Image"></td>
                  </tr>
                </table>
                {sfv_renderings}
            </div>
            <script>
                function toggleInvert() {{
                    var body = document.body;
                    var colorMode = document.getElementById('colorMode').value;
                    if (colorMode === 'inverted') {{
                        body.classList.add('inverted');
                    }} else {{
                        body.classList.remove('inverted');
                    }}
                }}
                document.addEventListener("DOMContentLoaded", function() {{
                    var downloadButton = document.querySelector('.download-button');
                    if (downloadButton) {{
                        downloadButton.addEventListener('click', function(event) {{
                            event.preventDefault();
                            fetch(this.href)
                                .then(response => {{
                                    if (!response.ok) {{
                                        document.getElementById('expired-banner').style.display = 'block';
                                    }} else {{
                                        window.location.href = this.href;
                                    }}
                                }});
                        }});
                    }}
                }});
            </script>
          </body>
        </html>
    '''

    return render_template_string(html_content)

@app.route('/download/<filename>')
def download_nfo(filename):

    filename_info_path = f"static/{filename}_filename.txt"
    nfo_path = f'static/{filename}.nfo'
    if not os.path.exists(nfo_path):
        return "", 404
    with open(filename_info_path, 'r') as f:
        original_filename = f.read()
    return send_file(nfo_path, as_attachment=True, download_name=original_filename)

@app.route('/download_sfv/<sfv_hexdig>')
def download_sfv(sfv_hexdig):
    # Determine the correct NFO hash by finding the relevant metadata file
    for root, dirs, files in os.walk('static'):
        for file in files:
            if file.endswith('_sfv_metadata.txt'):
                sfv_metadata_path = os.path.join(root, file)
                with open(sfv_metadata_path, 'r') as f:
                    for line in f:
                        if sfv_hexdig in line:
                            sfvname = line.split('|')[1]
                            sfv_data_path = f'static/{sfv_hexdig}.sfv'
                            if os.path.exists(sfv_data_path):
                                return send_file(sfv_data_path, as_attachment=True, download_name=sfvname)
    
    # If the file doesn't exist or wasn't found, return a 404 error
    return "", 404


@app.route('/fonts/<path:filename>')
def serve_fonts(filename):
    return send_from_directory('fonts', filename)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.root_path, 'favicon.ico', mimetype='image/vnd.microsoft.icon')
#-End of API stuff
#----------------------

# Cleanup files after NFO timeout.
# NOTE if you were to kill the process before this cleanup occurs, the files will remain in static.
# I use this as a way of easily testing without having to send new NFO data
def remove_file_after_delay(image_path, release_info_path, nfo_data_path, filename_info_path, saved_sfv_paths, delay):
    time.sleep(delay)
    if os.path.exists(image_path):
        os.remove(image_path)
    if os.path.exists(release_info_path):
        os.remove(release_info_path)
    if nfo_data_path and os.path.exists(nfo_data_path):
        os.remove(nfo_data_path)
    if filename_info_path and os.path.exists(filename_info_path):
        os.remove(filename_info_path)
    optional_fields_path = f"{os.path.splitext(image_path)[0]}_optional.txt"
    sfv_metadata_path = f"{os.path.splitext(image_path)[0]}_sfv_metadata.txt"
    if os.path.exists(optional_fields_path):
        os.remove(optional_fields_path)
    if os.path.exists(sfv_metadata_path):
        os.remove(sfv_metadata_path)
    for sfv in saved_sfv_paths:
        if os.path.exists(sfv['sfv_data_path']):
            os.remove(sfv['sfv_data_path'])
        if os.path.exists(sfv['sfv_image_path']):
            os.remove(sfv['sfv_image_path'])


if __name__ == '__main__':
    context = (le_fullchain, le_privkey)  # lets encrypt certs for ssl
    app.run(debug=debug_mode, port=server_port, host=host_ip, ssl_context=context, use_reloader=False)
