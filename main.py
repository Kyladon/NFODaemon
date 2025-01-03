# SPRE NFO Daemon
# v2.2

import os
import base64
import hashlib
import threading
import time
import ssl
import io
import zipfile
from sanic import Sanic
from sanic.response import json, file, html, text, HTTPResponse, raw
from sanic.exceptions import NotFound
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

appName = "SPRE"
appVersion = "2.2"
app = Sanic(appName)
sslFlag = True
VALID_TOKENS = set()

# Make sure all required folders exist
os.makedirs('static', exist_ok=True)
os.makedirs('fonts', exist_ok=True)
os.makedirs('themes', exist_ok=True)

######################################################################################################
#----------------------------------------------------------------------------------------------------
#-CONFIG VARIABLES-
#-Server settings
debug_mode = True                      # Debug Mode, dont forget to disable this once you are happy it works!
host_ip = '0.0.0.0'                    # Set the host IP interface. 0.0.0.0 for all. Dont forget to open to firewall.
server_port = 6789                     # Set the server port
timeout_seconds = 300                  # NFO timeout, how long before the files are deleted. 300=5mins

TOKEN_FILE = 'tokens.txt'              # Access tokens for REST API Access

#- Mediainfo override (if set then daemon will ignore mediainfo json (if any) and parse mediainfo file to populate the sidebar mediainfo)
#  If set to true this will also use the mediainfo file when there is no mediainfo json
mi_json_override = True

#-Lets Encrypt certificate path (make sure this is accessible to the daemon user)
le_certpath = "/etc/letsencrypt/live/your.domain.here/" # Should only need to update this path.

#-HTML Template variables
badge_color = "0, 150, 112"            # Badge background color (filenames on the main section). This overrides the default bootstrap theme's colour.
warning_badge_color = "252, 174, 124"  # Warning badge background color, used for mediainfo truncated warning flag
viewer_background_color = "0, 0, 0"    # Main viewer background color, default is black to match NFO render.
mi_background_color = "52,58,64"       # Mediainfo text background color

#-Tooltip labels. If desirable you can customize the text used on various things here rather than having to edit the code.
download_all_text = "Download nfo/sfv files as a release package (incl paths)"
truncated_mi_text = "This mediainfo was created using only the video data found in the first rar archive (.rar)"

#-NFO Render settings (Default config works well, recommend not changing these settings)
font_path = "fonts/cp437_IBM_VGA8.ttf" # Font to render NFOs. I find this is the best one to get a decent clean render
font_size = 16                         # 16 is the perfect size to render cp437_IBM_VGA8.
font_color = "white"                   # Font colour to render
background_color = "black"             # Background colour to render. Note, you should also adjust the HTML color scheme if you change this
#----------------------------------------------------------------------------------------------------
######################################################################################################

#- If you want you can also override some of the audio names in mediainfo, I do this purely to shorten them for the sidebar.
AUDIO_NAME_OVERRIDES = {
    "Dolby TrueHD with Dolby Atmos": "TrueHD with Atmos",
    "Dolby Digital Plus with Dolby Atmos": "DD+ with Atmos",
}

# Token Support
def load_tokens():
    global VALID_TOKENS
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as file:
            VALID_TOKENS = set(line.strip() for line in file)

def token_required(f):
    def decorated_function(request, *args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or token not in VALID_TOKENS:
            return json({"message": "Unauthorized"}, status=401)
        return f(request, *args, **kwargs)
    return decorated_function

def read_nfo_from_base64(base64_data):
    decoded_data = base64.b64decode(base64_data).decode('cp437')
    return decoded_data.splitlines()

def render_nfo_to_image(lines):
    font = ImageFont.truetype(font_path, font_size)
    
# Calculate image size to determine width for rendered output
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

# This will write all the sfv related files to disk for the http server to use
def save_sfv_files(sfvs, hexdig, save):
    saved_paths = []
    sfv_metadata_lines = []
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

        if save: #If we allow the user to download the original files
            # Save SFV data file
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
        else: #User is not allowed to download the original files.
            # No SFV file
            saved_paths.append({
                'sfv_data_path': None,
                'sfv_image_path': sfv_image_path,
                'sfvname': sfvname,
                'sfvpath': sfvpath,
                'sfv_hexdig': sfv_hexdig
            })

        # Add to metadata lines regardless of save
        # This ensures the viewer knows about these SFV images with the updated logic.
        sfv_metadata_lines.append(f"{sfv_hexdig}|{sfvname}|{sfvpath}\n")
    
    # Always write metadata, even if save=false
    sfv_metadata_path = f"static/{hexdig}_sfv_metadata.txt"
    with open(sfv_metadata_path, 'w') as f:
        f.writelines(sfv_metadata_lines)

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

# New mediainfo stuff...
def save_mi_files(mis, hexdig, save):
    saved_paths = []
    mi_metadata_lines = []
    for i, mi in enumerate(mis):
        mi_data = mi['mi_data']
        miname = mi['miname']
        mipath = mi.get('mipath', '')
        mitruncated = mi.get('mitruncated', False)  # New field
        mi_hash_input = mi_data + datetime.now().strftime("%Y%m%d%H%M%S%f")
        mi_hash_object = hashlib.md5(mi_hash_input.encode())
        mi_hexdig = mi_hash_object.hexdigest()

        if save: #If we allow the user to download the original files
            # Save MI data file
            mi_data_path = f"static/{mi_hexdig}.mi"
            with open(mi_data_path, 'wb') as f:
                f.write(base64.b64decode(mi_data))
            
            saved_paths.append({
                'mi_data_path': mi_data_path,
                'miname': miname,
                'mipath': mipath,
                'mi_hexdig': mi_hexdig,
                'mitruncated': mitruncated
            })
        else: #User is not allowed to download the original files.
            # No MI file
            saved_paths.append({
                'mi_data_path': None,
                'miname': miname,
                'mipath': mipath,
                'mi_hexdig': mi_hexdig,
                'mitruncated': mitruncated
            })

        # Add to metadata lines regardless of save
        # This ensures the viewer knows about these MI images with the updated logic.
        mi_metadata_lines.append(f"{mi_hexdig}|{miname}|{mipath}|{str(mitruncated)}\n")
    
    # Always write metadata, even if save=false
    mi_metadata_path = f"static/{hexdig}_mi_metadata.txt"
    with open(mi_metadata_path, 'w') as f:
        f.writelines(mi_metadata_lines)

    return saved_paths

def load_mi_metadata(hexdig):
    mi_metadata_path = f"static/{hexdig}_mi_metadata.txt"
    saved_paths = []
    if os.path.exists(mi_metadata_path):
        with open(mi_metadata_path, 'r') as f:
            for line in f:
                mi_hexdig, miname, mipath, mitruncated_str   = line.strip().split('|')
                mi_data_path = f"static/{mi_hexdig}.mi"
                mitruncated = mitruncated_str.lower() == 'true'
                saved_paths.append({
                    'mi_data_path': mi_data_path,
                    'miname': miname,
                    'mipath': mipath,
                    'mi_hexdig': mi_hexdig,
                    'mitruncated': mitruncated
                })
    return saved_paths

def handle_mi_encode_settings(mi_text):
    # Returns modified version of mi_text with the Encoding settings line split for display purposes
    # Does not affect actual mediainfo file download if applicable
    lines = mi_text.splitlines()
    new_lines = []

    for line in lines:
        if line.strip().startswith("Encoding settings"):
            # Find the first colon (":") so we can split
            colon_index = line.find(':')
            if colon_index != -1:
                left_part  = line[:colon_index+1]  # include the colon
                right_part = line[colon_index+1:].strip()

                # Start splitting options where required (encoding settings)
                segments = right_part.split(" / ")

                # The first segment gets appended to the left_part
                # so it looks like:  Encoding settings ... : cabac=1
                if segments:
                    first_segment = segments[0]
                    new_lines.append(f"{left_part} {first_segment}")

                # For subsequent segments, indent them to align with the colon
                # so it looks like:  (spaces) : ref=4
                # Figure out how many spaces are before the colon so we can replicate that indentation.
                indent_length = len(left_part) - 1  # minus 1 so the colon lines up  with the colon of the first line
                indentation = " " * indent_length
                for seg in segments[1:]:
                    new_lines.append(f"{indentation}: {seg}")
            else:
                # If no colon was found, just keep the line as is
                new_lines.append(line)
        else:
            # For all other lines, leave them alone
            new_lines.append(line)

    # Rejoin with newlines
    return "\n".join(new_lines)


def override_commercial_name(name: str) -> str:
    #If 'name' is in the AUDIO_NAME_OVERRIDES dic then return the shorter name
    return AUDIO_NAME_OVERRIDES.get(name, name)

def first_val(kv_map, key):
    # Return the first stored value for 'key' (or empty string) from kv_map
    return kv_map.get(key, [])[0] if key in kv_map else ""

def normalized_section_name(sec_name):
    # Determine if sec_name is 'Video', 'Audio', or 'Text', ignoring #1, #2, etc.
    # Return 'other' if it doesn't match any known sections.
    name_lower = sec_name.lower()
    if 'video' in name_lower:
        return 'video'
    elif 'audio' in name_lower:
        return 'audio'
    elif 'text' in name_lower:
        return 'text'
    return 'other'

def parse_mediainfo_file(mi_data):
    # Parse raw .mi text into a dictionary structure similar to our JSON based mediainfo
    #    {
    #      "video": [ { ...track1... }, { ...track2... }, ... ],
    #      "audio": [ { ... }, ... ],
    #      "text":  [ { ... }, ... ]
    #    }
    # Only the relevant lines are extracted (ignoring General for example).

    lines = mi_data.splitlines()
    sections = []
    current_section_name = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            # Empty line => end current section
            current_section_name = None
            continue

        if ':' not in line:
        # No colon = this is a new section header (e.g. "General", "Video #1", etc.)
            current_section_name = line
            sections.append((current_section_name, {}))
            continue

        # Otherwise, it's a key:value line
        key_part, val_part = line.split(':', 1)
        key = key_part.strip()
        val = val_part.strip()

        if sections and current_section_name:
            sec_dict = sections[-1][1]
            if key not in sec_dict:
                sec_dict[key] = []
            sec_dict[key].append(val)

    mi_struct = {"video": [], "audio": [], "text": []}

    # Go through each section, transform into "video", "audio", or "text" track info
    for (sec_name, kv_map) in sections:
        sec_type = normalized_section_name(sec_name)
        if sec_type == 'other':
            # For example 'General' or if unknown => skip
            continue

        track_info = {}
        if sec_type == 'video':
            # Combine format info: Encoded_Library_Name, Format profile, Format
            encode_lib = first_val(kv_map, "Encoded_Library_Name")
            format_profile = first_val(kv_map, "Format profile")
            fmt = first_val(kv_map, "Format")
            parts = [p for p in [encode_lib, format_profile, fmt] if p]
            track_info["format"] = " ".join(parts)  # e.g "x265 Main 10@L5.1@High HEVC"

            # resolution = "Width x Height" (strip non-digits if any, rare)
            w = first_val(kv_map, "Width")
            h = first_val(kv_map, "Height")
            w_clean = ''.join(ch for ch in w if ch.isdigit())
            h_clean = ''.join(ch for ch in h if ch.isdigit())
            track_info["resolution"] = f"{w_clean}x{h_clean}" if (w_clean and h_clean) else ""

            # bit rate = numeric string only
            br = first_val(kv_map, "Bit rate")
            br_clean = ''.join(ch for ch in br if ch.isdigit())
            track_info["bitrate"] = br_clean

            # bit rate mode
            track_info["bitrate_mode"] = first_val(kv_map, "Bit rate mode")

            # pick "x h x min" style from all Durations if found
            all_durations = kv_map.get("Duration", [])
            pretty_dur = ""
            for d_line in all_durations:
                if " h " in d_line:
                    pretty_dur = d_line
                    break
            if not pretty_dur and all_durations:
                pretty_dur = all_durations[0]
            track_info["duration"] = "0"  # numeric placeholder if you want
            track_info["duration_pretty"] = pretty_dur

            mi_struct["video"].append(track_info)

        elif sec_type == 'audio':
            comm_name = first_val(kv_map, "Commercial name")
            # override the long name if required, as per override_commercial_name variable below config options
            comm_name = override_commercial_name(comm_name)
            track_info["format"] = comm_name if comm_name else first_val(kv_map, "Format")

            # channels 
            chans = ""
            for c_line in kv_map.get("Channel(s)", []):
                if "channel" in c_line.lower():
                    chans = c_line
                    break
            track_info["channels"] = chans

            # BitRate
            br = first_val(kv_map, "Bit rate")
            br_clean = ''.join(ch for ch in br if ch.isdigit())
            track_info["BitRate"] = br_clean

            # bit rate mode
            track_info["bitrate_mode"] = first_val(kv_map, "Bit rate mode")

            # language = first instance since we are not proving a complete mediainfo experience on the sidebar....
            track_info["language"] = first_val(kv_map, "Language")
            mi_struct["audio"].append(track_info)

        elif sec_type == 'text':
            track_info["format"]   = first_val(kv_map, "Format")
            track_info["title"]    = first_val(kv_map, "Title")
            track_info["language"] = first_val(kv_map, "Language")

            mi_struct["text"].append(track_info)

    return mi_struct


# Finally, a way to check on when your LetsEncrypt expires
# We have this mostly for the new status endpoint to handle recycling of the daemon externally if required
def get_ssl_expiry_date(cert_path):
    try:
        cert_info = ssl._ssl._test_decode_cert(cert_path)
        not_after_str = cert_info.get('notAfter')
        if not_after_str:
            dt = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
            return dt.strftime("%Y-%m-%d")
        return None
    except:
        return None

#----------------------
#-API Stuff
@app.route('/upload_nfo', methods=['POST'], name='upload_nfo_route')
@token_required
async def upload_nfo(request):
    required_fields = ['nfo_data', 'release', 'filename', 'save']
    data = request.json

    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return json({"url": None, "message": f"Missing fields: {', '.join(missing_fields)}"}, status=400)

    try:
        base64_data = data['nfo_data']
        release = data['release']
        filename = data['filename']
        save = data['save']
        date = data.get('date', '')
        files = data.get('files', '')
        size = data.get('size', '')
        section = data.get('section', '')
        sfvs = data.get('sfvs', [])
        mediainfos = data.get('mediainfos', []) 
        lines = read_nfo_from_base64(base64_data)
        image = render_nfo_to_image(lines)
       
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        
# create a unique hash for our files per request
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
            f.write(f"{date}\n{files}\n{size}\n{section}")
        
# Save SFV files if provided
        saved_sfv_paths = []
        if sfvs:
            saved_sfv_paths = save_sfv_files(sfvs, hexdig, save)
            
# Save mediainfo json data if there is any. 
        import json as pjson
        mediainfo = data.get('mediainfo', [])
        mediainfo_path = f"static/{hexdig}_mediainfo.json"
        with open(mediainfo_path, 'w') as f:
            pjson.dump(mediainfo, f)

# Save mediainfo files if provided
        saved_mi_paths = []
        if mediainfos:
            saved_mi_paths = save_mi_files(mediainfos, hexdig, save)

# finally we update our stats. Very basic count tracker
        count_path = 'count.txt'
        if not os.path.exists(count_path):
            with open(count_path, 'w') as f:
                f.write('0')
        with open(count_path, 'r') as f:
            current_count = int(f.read().strip() or '0')
        current_count += 1
        with open(count_path, 'w') as f:
            f.write(str(current_count))

# Serve the web page
        threading.Thread(target=CleanupFiles, args=(image_path, release_info_path, nfo_data_path, filename_info_path, saved_sfv_paths, saved_mi_paths, timeout_seconds)).start() 
        return json({"url": f"/viewer/{hexdig}", "message": "Success"})
        
    except Exception as e:
        return json({"url": None, "message": "Error"}, status=500)

# New status endpoint. Very basic, requires token access
@app.route('/status', methods=['GET'], name='status_route')
@token_required
async def status_endpoint(request):
    count_path = 'count.txt'
# Read the current count from count.txt, or default to 0
    if os.path.exists(count_path):
        with open(count_path, 'r') as f:
            nfoServed = int(f.read().strip() or '0')
    else:
        nfoServed = 0

    sslExpiry = None
# Check when SSL cert expires, since LetsEncrypt only last 90 days this can help trigger something if required.
    if sslFlag:
        le_fullchain = os.path.join(le_certpath, "fullchain.pem")
        sslExpiry = get_ssl_expiry_date(le_fullchain)

    return json({
        "nfoServed": nfoServed,
        "sslExpiry": sslExpiry
    })

# Our main function, the viewer aka HTTP server on request
@app.route('/viewer/<filename>')
async def serve_image(request, filename):

    # We configure Jinja2 for templating our HTML now
    template_env = Environment(loader=FileSystemLoader('.'))

    image_path = f"static/{filename}.png"
    release_info_path = f"static/{filename}.txt"
    filename_info_path = f"static/{filename}_filename.txt"
    optional_fields_path = f"static/{filename}_optional.txt"
    nfo_data_path = f"static/{filename}.nfo"
    mediainfo_path = f"static/{filename}_mediainfo.json"

    # If hash no longer exists, present a basic page saying not found.
    if not os.path.exists(image_path) or not os.path.exists(release_info_path) or not os.path.exists(filename_info_path):
        template = template_env.from_string('''
            <!doctype html>
            <html lang="en">
              <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
                <title>Hash not found</title>
                <link rel="stylesheet" href="{{ url_for('serve_fonts', filename='roboto.css') }}">
                <link rel="stylesheet" href="{{ url_for('serve_themes', filename='bootstrap.min.css') }}">
                 <style>
                    body {
                        background-color: rgb({{ viewer_background_color }});
                        color: white;
                        font-family: 'Roboto', sans-serif;
                        padding-top: 20px;
                        padding-left: 30px;
                    }
                    img {
                       display: block;
                       max-width: 100%;
                       height: auto;
                       border-radius: 10px;
                    }
                </style>
              </head>
              <body>
                  <h1>Hash not found</h1>
              </body>
            </html>
        ''')
        return html(template.render(url_for=app.url_for), status=404)

    # Load main metadata
    with open(release_info_path, 'r') as f:
        release = f.read()

    with open(filename_info_path, 'r') as f:
        original_filename = f.read()

    date, files, size, section = '', '', '', ''
    if os.path.exists(optional_fields_path):
        with open(optional_fields_path, 'r') as f:
            optional_fields = f.read().splitlines()
            if len(optional_fields) > 0:
                date = optional_fields[0]
            if len(optional_fields) > 1:
                files = optional_fields[1]
            if len(optional_fields) > 2:
                size = f"{optional_fields[2]} MB" if optional_fields[2] else ""
            if len(optional_fields) > 3:
                section = optional_fields[3]
    
    # This prepares the basic information for the sidebar 
    date_info = f'<div><img src="{app.url_for("serve_svg_icons", filename="date.svg")}" class="icon"> {date}</div>' if date else ''
    file_size_info = ""
    if files and size:
        file_size_info = f'<div><img src="{app.url_for("serve_svg_icons", filename="files.svg")}" class="icon"> {files} Files / {size}</div>'
    elif files:
        file_size_info = f'<div><img src="{app.url_for("serve_svg_icons", filename="files.svg")}" class="icon"> {files} Files / </div>'
    elif size:
        file_size_info = f'<div><img src="{app.url_for("serve_svg_icons", filename="files.svg")}" class="icon"> {size}</div>'
    section_info = f'<div><img src="{app.url_for("serve_svg_icons", filename="section.svg")}" class="icon"> {section.upper()}</div>' if section else ''

    # Check if hash exists, and download NFO button handler.
    if os.path.exists(nfo_data_path):
        nfo_download_url = app.url_for('download_nfo', filename=filename)
        download_button = f'''
                <a id="nfoDownloadButton" href="{nfo_download_url}" class="btn btn-sm download-button align-icon-center" style="align-self: center; width: 1.5em; height: 1.5em; display: flex; justify-content: center; align-items: center; padding: 0;">
                <img src="{app.url_for('serve_svg_icons', filename='save.svg')}" class="icon" alt="Download NFO">
            </a>
        '''
        expired_message = '<div id="expired-banner" class="expired-banner text-center" style="display:none; font-weight:bold; color:red;">Hash has expired</div>'
    else:
        download_button = ''
        expired_message = '<div id="expired-banner" class="expired-banner text-center" style="display:none; font-weight:bold; color:red;">Hash has expired</div>'

    # Render NFO badges with the download button on the same line
    nfo_badges = f'''
        <div id="nfoBadge" style="position: relative; padding-left: 10px; scroll-margin-top: 86px; margin-top: 5px; display: flex; gap: 5px; flex-wrap: wrap; align-items: center;">
    '''
    # Add the download button first
    nfo_badges += download_button

    # Add the NFO filename badge
    nfo_badges += f'''
        <span class="badge" style="margin-bottom: 0px; align-self: center; background-color: rgba({badge_color}, var(--bs-bg-opacity, 1)) !important;">{original_filename}</span>
    </div>
    '''

    # Load SFV metadata for display, if applicable
    saved_sfv_paths = load_sfv_metadata(filename)
    sfv_renderings = ''
    for sfv in saved_sfv_paths:
        sfv_filename = sfv['sfvname']
        sfv_image_path = sfv['sfv_image_path']
        sfv_path = sfv['sfvpath']
        sfv_hexdig = sfv['sfv_hexdig']

        # sfv_badges logic
        sfv_data_path = f"static/{sfv_hexdig}.sfv"
        if os.path.exists(sfv_data_path):
            # SFV file exists
            sfv_download_url = app.url_for('download_sfv', sfv_hexdig=sfv_hexdig)
            sfv_download_button = f'''
                <a href="{sfv_download_url}" class="btn btn-sm download-button sfvDownloadButton" style="align-self: center; width: 1.5em; height: 1.5em; display: flex; justify-content: center; align-items: center; padding: 0;">
                    <img src="{app.url_for('serve_svg_icons', filename='save.svg')}" class="icon" alt="Download SFV">
                </a>
            '''
        else:
            sfv_download_button = ""

        sfv_badges = f'''
            <div id="sfvBadge_{sfv_hexdig}" style="position: relative; padding-left: 10px; scroll-margin-top: 56px; display: flex; gap: 5px; flex-wrap: wrap; align-items: center;">
        '''

        # Add the download button first
        if sfv_download_button:
            sfv_badges += sfv_download_button

        # Add the SFV path badge if it exists
        if sfv_path:
            sfv_badges += f'''
                <span class="badge" style="background-color: rgba({badge_color}, var(--bs-bg-opacity, 1)) !important;">{sfv_path}</span>
            '''

        # Add the SFV filename badge
        sfv_badges += f'''
            <span class="badge" style="background-color: rgba({badge_color}, var(--bs-bg-opacity, 1)) !important;">{sfv_filename}</span>
        </div>
        '''

        sfv_renderings += f'''
        <div class="divider divi"><hr></div>
        {sfv_badges}
        <div style="padding-left: 10px;">
            <img src="/static/{sfv_hexdig}.png" alt="SFV Image">
        </div>
        '''

    # Load mediainfo JSON info for sidebar if applicable
    mediainfo = []
    saved_mi_paths = load_mi_metadata(filename)
    mediainfo_rendering = ''

    # Load existing mediainfo JSON, if it exists)
    if os.path.exists(mediainfo_path):
        import json as pjson
        with open(mediainfo_path, 'r') as f:
            mediainfo = pjson.load(f)  #note: [ { 'video': [...], 'audio': [...], 'text': [...] } ]

    # Now handle the override logic
    video_tracks = []
    audio_tracks = []
    text_tracks = []

    if mi_json_override and saved_mi_paths:
        # If we have at least one .mi file, parse it
        first_mi_file_path = saved_mi_paths[0]['mi_data_path']
        if first_mi_file_path and os.path.exists(first_mi_file_path):
            with open(first_mi_file_path, 'r') as f:
                raw_mi_data = f.read()
            parsed_mi_struct = parse_mediainfo_file(raw_mi_data)

            video_tracks = parsed_mi_struct.get('video', [])
            audio_tracks = parsed_mi_struct.get('audio', [])
            text_tracks  = parsed_mi_struct.get('text', [])
        else:
            # fallback to our JSON approach if the .mi file is missing
            if mediainfo:
                video_tracks = mediainfo[0].get('video', [])
                audio_tracks = mediainfo[0].get('audio', [])
                text_tracks  = mediainfo[0].get('text', [])
    else:
        # If override is false or no .mi files = use JSON approach
        if mediainfo:
            video_tracks = mediainfo[0].get('video', [])
            audio_tracks = mediainfo[0].get('audio', [])
            text_tracks  = mediainfo[0].get('text', [])

    mediainfo_lines = []

    # Video
    if video_tracks:
        v = video_tracks[0]
        combined_info = v.get('format','')  
        if combined_info:
            mediainfo_lines.append(f'<div><img src="{app.url_for("serve_svg_icons", filename="video.svg")}" class="icon"> {combined_info}</div>')
        
        resolution = v.get('resolution','')
        if resolution:
            mediainfo_lines.append(f'<div><img src="{app.url_for("serve_svg_icons", filename="video.svg")}" class="icon"> {resolution}</div>')
        
        bitrate_str = v.get('bitrate','0')
        try:
            bitrate_int = int(bitrate_str)
            bitrate_kb = round(bitrate_int / 1000)
            bitrate_formatted = f"{bitrate_kb} kb/s Bitrate"
        except ValueError:
            bitrate_formatted = ''
        if bitrate_formatted:
            mediainfo_lines.append(f'<div><img src="{app.url_for("serve_svg_icons", filename="video.svg")}" class="icon"> {bitrate_formatted}</div>')

        pretty_duration = v.get('duration_pretty','')
        if pretty_duration:
            mediainfo_lines.append(f'<div><img src="{app.url_for("serve_svg_icons", filename="video.svg")}" class="icon"> {pretty_duration}</div>')

    # Audio
    if audio_tracks:
        a = audio_tracks[0]
        fmt = a.get('format','')
        chans = a.get('channels','')
        if fmt and chans:
            mediainfo_lines.append(f'<div><img src="{app.url_for("serve_svg_icons", filename="speaker.svg")}" class="icon"> {fmt} {chans}</div>')
        elif fmt:
            mediainfo_lines.append(f'<div><img src="{app.url_for("serve_svg_icons", filename="speaker.svg")}" class="icon"> {fmt}</div>')

        # bitrate
        br_str = a.get('BitRate','0')
        try:
            br_int = int(br_str)
            br_kb  = round(br_int / 1000)
            br_formatted = f"{br_kb} kb/s"
        except ValueError:
            br_formatted = ''

        br_mode = a.get('bitrate_mode','')
        if br_formatted:
            line_str = br_formatted
            if br_mode:
                line_str += f' {br_mode}'
            # Language
            lang = a.get('language','')
            if lang:
                line_str += f' <i>&nbsp;{lang}</i>'
            mediainfo_lines.append(f'<div><img src="{app.url_for("serve_svg_icons", filename="speaker.svg")}" class="icon"> {line_str}</div>')

    # Text/Subtitles
    for t in text_tracks:
        fmt   = t.get('format','')
        title = t.get('title','')
        lang  = t.get('language','')
        line_str = fmt
        if title:
            line_str += f' {title}'
        if lang:
            line_str += f' <i>&nbsp;{lang}</i>'
        if line_str.strip():
            mediainfo_lines.append(f'<div><img src="{app.url_for("serve_svg_icons", filename="subs.svg")}" class="icon"> {line_str}</div>')

    mediainfo_rendering = '\n'.join(mediainfo_lines)
    
    mediainfo_info = f'<h6>Mediainfo</h6>\n{mediainfo_rendering}' if mediainfo_rendering else ''


    # Load mediainfo files to display in the main window, if there are any...
    mi_renderings = ''
    for mi in saved_mi_paths:
        mi_filename = mi['miname']
        mi_path = mi['mipath']
        mi_hexdig = mi['mi_hexdig']
        mitruncated = mi.get('mitruncated', False)  

        # mi_badges logic
        mi_data_path = f"static/{mi_hexdig}.mi"
        if os.path.exists(mi_data_path):
            # MI file exists
            mi_download_url = app.url_for('download_mi', mi_hexdig=mi_hexdig)
            mi_download_button = f'''
                <a href="{mi_download_url}" class="btn btn-sm download-button miDownloadButton" style="align-self: center; width: 1.5em; height: 1.5em; display: flex; justify-content: center; align-items: center; padding: 0;">
                    <img src="{app.url_for('serve_svg_icons', filename='save.svg')}" class="icon" alt="Download MI">
                </a>
            '''
        else:
            mi_download_button = ""

        mi_badges = f'''
            <div id="miBadge_{mi_hexdig}" style="position: relative; padding-left: 10px; scroll-margin-top: 56px; display: flex; gap: 5px; flex-wrap: wrap; align-items: center;">
        '''

        # Add the download button first
        if mi_download_button:
            mi_badges += mi_download_button

        # Add the MI path badge if it exists
        if mi_path:
            mi_badges += f'''
                <span class="badge" style="background-color: rgba({badge_color}, var(--bs-bg-opacity, 1)) !important;">{mi_path}</span>
            '''

        # Add the MI filename badge
        mi_badges += f'''
            <span class="badge" style="background-color: rgba({badge_color}, var(--bs-bg-opacity, 1)) !important;">{mi_filename}</span>
        '''
        # flag our truncated mediainfo files
        if mitruncated:
            mi_badges += f'''
                <span class="badge" style="background-color: rgba({warning_badge_color}, var(--bs-bg-opacity, 1)) !important;" data-toggle="tooltip" title="{truncated_mi_text}">Truncated</span>
            '''

        mi_badges += '''
            </div>
        '''
    
        # Read the mi data for the codeblock
        mi_data = ""
        if os.path.exists(mi_data_path):
            with open(mi_data_path, 'r') as f:
                mi_data = f.read()

            # Transform *just* for display:
            pretty_mi_data = handle_mi_encode_settings(mi_data)

            mi_renderings += f'''
            <div class="divider divi"><hr></div>
            {mi_badges}
            <div class="mi-container">
                <pre class="mi-block">{pretty_mi_data}</pre>
            </div>
            '''

    # File listing for sidebar, and scroll locations.
    file_list_html = ''
    if os.path.exists(nfo_data_path):
        file_list_html += f'''
        <div>
            <img src="{app.url_for("serve_svg_icons", filename="text-file.svg")}" class="icon" alt="File Icon">
            <a href="#nfoBadge">{original_filename}</a>
        </div>
        '''

    for sfv in saved_sfv_paths:
        sfv_filename = sfv['sfvname']
        sfv_hexdig = sfv['sfv_hexdig']
        file_list_html += f'''
        <div>
            <img src="{app.url_for("serve_svg_icons", filename="text-file.svg")}" class="icon" alt="File Icon">
            <a href="#sfvBadge_{sfv_hexdig}">{sfv_filename}</a>
        </div>
        '''

    for mi in saved_mi_paths:
        mi_filename = mi['miname']
        mi_hexdig = mi['mi_hexdig']
        file_list_html += f'''
        <div>
            <img src="{app.url_for("serve_svg_icons", filename="text-file.svg")}" class="icon" alt="File Icon">
            <!--<a href="#miBadge_{mi_hexdig}">full.mediainfo</a> -->
            <a href="#miBadge_{mi_hexdig}">{mi_filename}</a>
        </div>
        '''    


    files_info = f'<h6>Files</h6>\n{file_list_html}' if file_list_html else ''

    # Download all button logic
    download_all_button = ""
    if os.path.exists(nfo_data_path):
        download_all_url = app.url_for('download_all', filename=filename)
        download_all_button = f'''
            <div class="btn-download-container"><div class="download-divider"></div>
            <a href="{download_all_url}" id="allDownloadButton" class="btn btn-sm download-button align-icon-center" data-toggle="tooltip" data-delay=500 data-placement="left" title="{download_all_text}">
            <img src="{app.url_for('serve_svg_icons', filename='package.svg')}" class="icon" alt="Download Package">
            </a></div>
        '''

    # Continue constructing the html template
    template = template_env.from_string('''
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
            <title>{{ release }}</title>
            <link rel="stylesheet" href="{{ url_for('serve_fonts', filename='roboto.css') }}">
            <link rel="stylesheet" href="{{ url_for('serve_themes', filename='bootstrap.min.css') }}">
            <style>
                @font-face {
                    font-family: 'Roboto Mono';
                    src: url('{{ url_for("serve_fonts", filename="RobotoMono.ttf") }}') format('truetype');
                }
                body {
                    background-color: rgb({{ viewer_background_color }});
                    color: white;
                    color-scheme: dark light;
                    font-family: 'Roboto', sans-serif;
                    padding-top: 0;
                    padding-left: 0;

                }
                img {
                    display: block;
                    max-width: fit-content;
                    height: auto;
                }
                #nfoImage {
                    max-width: none;
                }
                .inverted {
                    filter: invert(100%) hue-rotate(180deg);
                }
                #main-content {
                    margin-left: 300px;
                    padding-left: 20px;
                    padding-top: 56px;
                    max-height: calc(100vh) /* Uncomment this if you want the horizontal scrollbar to appear at the bottom of the window rather than bottom of the data */
                    overflow: auto; 
                    overflow-x: overlay; /* Match document scrollbar behavior */
                }
                #sidebar {
                    position: fixed;
                    top: 40px;
                    left: 0;
                    width: 300px;
                    height: calc(100vh - 56px);
                    background-color: #212529;
                    padding: 0;
                    display: flex;
                    flex-direction: column;
                    max-height: calc(100vh);   /* Prevent sidebar from exceeding view */
                    height: auto;
                }
                 #sidebar h6 {
                    background-color: #212529;
                    border-bottom: 1px solid #343a40;
                    font-size: 0.95rem;
                    font-weight:bold;
                    margin-bottom: 0.25rem;
                    padding: 4px 0px;
                    text-transform: uppercase;
                    box-sizing: border-box;
                    width: 100%;
                    line-height:1;
                    text-align: center;
                }
                
                #sidebar > div {
                    padding: 4px 8px;
                    border-bottom: 1px solid #343a40;
                    font-size: 0.95rem; /* Reduced Font Size for Sidebar Filenames */
                    line-height: 1.2;
                    width:100%;
                    box-sizing: border-box;
                    display: flex;
                    align-items: center;
                    min-height: 1.5em;
                    overflow-wrap: normal;
                    white-space: nowrap;
                    
                }
                 #sidebar > div:nth-child(odd) {
                    background-color: #343a40;
                }
               #sidebar > div a {
                   font-size: 0.85rem;
                   font-family: 'Roboto Mono', monospace;
                }
                .icon {
                    height: 1.5em;
                    filter: invert(1);
                    margin-right: 5px;
                    width: auto; /* This is key to ensure that the SVG is not squished*/
                    max-height: 1.5em; /*This is key to ensuring that the height does not become too large*/
                }
                 .nav-bar{
                    width:100%;
                    position:fixed;
                    z-index:1000;
                    background-color: #343a40;
                    padding: 5px 15px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    height: 40px;
                }
                .nav-bar .navbar-brand {
                    color: white;
                    font-size: 1.25rem;
                    font-weight: bold;
                    padding-bottom: 2px;
                    margin: 0;
                    overflow: hidden; /* hide overflowing content*/
                    text-overflow: ellipsis; /* ellipsis "..." for overflowing text */
                    white-space: nowrap; /* prevent line break */
                    max-width: calc(100% - 100px); /* adjust the subtraction to accommodate the download buttons */
                }
                 .badge{
                    font-size: 1rem;
                    --bs-bg-opacity: 1;
                }
                .mi-container {
                    padding-left: 10px;
                    margin-top: 10px;
                }

                .mi-block {
                    display: inline-block;
                    background-color: rgb({{ mi_background_color }});
                    font-family: 'Roboto Mono', monospace;
                    padding: 10px;
                    margin: 0;
                    white-space: pre;
                    /*overflow-x: auto;      */
                    border-radius: 5px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.25);
                    /* The following kinda look nice, optionally uncomment both :)*/
                    /*border-left: 4px solid #7ea9ff;*/
                    /*color: #f8f9fa;*/
                }
                /* This will shift all left tooltips a bit further to the left so they are not RIGHT on the object */
                .tooltip.bs-tooltip-left {
                    margin-right: 20px;
                }
                .download-divider {
                    border-left: 1px solid #555;
                    height: 40px; /* Match the button's height */
                    margin-right: 5px;
                    transition: background-color 0.3s ease;
                }
                .btn-download-container {
                display: flex;
                align-items: center;
                margin-right: -15px; 
                transition: background-color 0.3s ease;
                }
                .btn-download-container:hover{
                    background-color: rgb({{ badge_color }});
                    margin-right: -15px;
                } 


            </style>
        </head>
        <body>
            <nav class="nav-bar">
                <a class="navbar-brand" href="#">{{ release }}</a>
                <div style="display: flex; align-items: center; height: 100%;">
                   {{ download_all_button | safe }}
                </div>
            </nav>

            <div id="sidebar">
                <h6>Release Info</h6>
                {{ date_info | safe }}
                {{ file_size_info | safe }}
                {{ section_info | safe }}
                {{ mediainfo_info | safe }}
                {{ files_info | safe }}
            </div>

            <div id="main-content">
                {{ expired_message|safe }}
                {{nfo_badges|safe}}
                <div style="padding-left: 10px;"><img id="nfoImage" src="/static/{{ filename }}.png" alt="NFO Image"></div>
                {{ sfv_renderings|safe }}
                {{ mi_renderings|safe }}
                <div style="height: 250px;"></div> <!-- Some needed padding especially if SFV's are small... -->
            </div>

            <script src="/themes/jquery-3.5.1.slim.min.js"></script>
            <script src="/themes/popper.min.js"></script>
            <script src="/themes/bootstrap.min.js"></script>
           
            <script>
              document.addEventListener('DOMContentLoaded', function() {
                $(function () {
                $('[data-toggle="tooltip"]').tooltip()
                });
                const truncationCache = new Map(); // Cache to store bestLength per max_em_width
                const minLength = 5;
                const maxLength = 32; // Maximum length of characters before truncation 
                function updateFilenameTruncation() {
                    const sidebarDivs = document.querySelectorAll('#sidebar > div');
                    if (sidebarDivs.length === 0) return;
                    const firstDiv = sidebarDivs[0];
                    const divWidth = parseFloat(window.getComputedStyle(firstDiv).width) / parseFloat(window.getComputedStyle(firstDiv).fontSize);
                    // Ensure we compute the best length for this width only once
                    if (!truncationCache.has(divWidth)) {
                        let computedLength = Math.round(divWidth * 1.2);
                        // Ensure length is within min/max bounds
                        computedLength = Math.max(minLength, Math.min(computedLength, maxLength));
                        truncationCache.set(divWidth, computedLength);
                    }
                    const bestLength = truncationCache.get(divWidth);
                    sidebarDivs.forEach(div => {
                        const filenameLink = div.querySelector('a');
                        if (!filenameLink) return;
                        const originalName = filenameLink.textContent;
                        const truncatedName = applyTruncation(originalName, bestLength);
                        filenameLink.textContent = truncatedName;
                    });
                }

                function applyTruncation(filename, bestLength) {
                    const nameAndExt = filename.split('.');
                    const hasExt = nameAndExt.length > 1;
                    const ext = hasExt ? `.${nameAndExt.pop()}` : '';
                    const baseName = nameAndExt.join('.');
                    // Check for mediainfo extension 
                    const isMediainfo = filename.toLowerCase().endsWith(".mediainfo");
                    // For mediainfo files, we want a shorter truncation otherwise it extends beyond the sidebar.
                    if (isMediainfo) {
                        const aggressiveLength = Math.min(bestLength - 5, 18); 
                        if (baseName.length > aggressiveLength)
                        {
                            return baseName.substring(0, aggressiveLength) + '..' + ext;
                        }else{
                        return filename;
                        }
                        
                    } else if (baseName.length > bestLength) {
                        return baseName.substring(0, bestLength) + '..' + ext;
                    } else {
                        return filename;
                    }
                }
                // Update the truncation on initial load
                updateFilenameTruncation();
                // Update the truncation on window resize
                window.addEventListener('resize', function() {
                    truncationCache.clear(); // Clear the cache on resize to recalculate
                    updateFilenameTruncation();
                });
              });
            </script>
        </body>
        </html>
    ''')

    return html(template.render(
        release=release,
        date=date,
        files=files,
        size=size,
        section=section,
        sfv_renderings=sfv_renderings,
        mi_renderings = mi_renderings,
        filename=filename,
        mediainfo_rendering=mediainfo_rendering,
        download_button=download_button,
        expired_message=expired_message,
        file_size_info=file_size_info,
        file_list_html=file_list_html,
        original_filename = original_filename,
        nfo_badges = nfo_badges,
        download_all_button=download_all_button,
        url_for=app.url_for,
        date_info=date_info,
        section_info=section_info,
        mediainfo_info=mediainfo_info,
        files_info=files_info,
        badge_color = badge_color,
        viewer_background_color = viewer_background_color,
        mi_background_color = mi_background_color
    ))
    
@app.route('/download/<filename>')
async def download_nfo(request, filename):
    # Download NFO file
    filename_info_path = f"static/{filename}_filename.txt"
    nfo_path = f'static/{filename}.nfo'
    if not os.path.exists(nfo_path):
        return text("", status=404)
    with open(filename_info_path, 'r') as f:
        original_filename = f.read()
    return await file(nfo_path, filename=original_filename, headers={"Content-Disposition": f"attachment; filename={original_filename}"})

@app.route('/download_sfv/<sfv_hexdig>')
async def download_sfv(request, sfv_hexdig):
    # Determine the correct NFO hash by finding the relevant metadata file
    for root, dirs, files in os.walk('static'):
        for sfvFile in files:
            if sfvFile.endswith('_sfv_metadata.txt'):
                sfv_metadata_path = os.path.join(root, sfvFile)
                with open(sfv_metadata_path, 'r') as f:
                    for line in f:
                        if sfv_hexdig in line:
                            sfvname = line.split('|')[1]
                            sfv_data_path = f'static/{sfv_hexdig}.sfv'
                            if os.path.exists(sfv_data_path):
                                return await file(sfv_data_path, filename=sfvname, headers={"Content-Disposition": f"attachment; filename={sfvname}"})

    # If the file doesn't exist or wasn't found, return a 404 error
    return text("", status=404)

@app.route('/download_mi/<mi_hexdig>')
async def download_mi(request, mi_hexdig):
    # Determine the correct NFO hash by finding the relevant metadata file
    for root, dirs, files in os.walk('static'):
        for miFile in files:
            if miFile.endswith('_mi_metadata.txt'):
                mi_metadata_path = os.path.join(root, miFile)
                with open(mi_metadata_path, 'r') as f:
                    for line in f:
                        if mi_hexdig in line:
                            miname = line.split('|')[1]
                            mi_data_path = f'static/{mi_hexdig}.mi'
                            if os.path.exists(mi_data_path):
                                return await file(mi_data_path, filename=miname, headers={"Content-Disposition": f"attachment; filename={miname}"})

    # If the file doesn't exist or wasn't found, return a 404 error
    return text("", status=404)


# Download all package...
@app.route('/download_all/<filename>')
async def download_all(request, filename):
    image_path = f"static/{filename}.png"
    release_info_path = f"static/{filename}.txt"
    filename_info_path = f"static/{filename}_filename.txt"
    nfo_data_path = f"static/{filename}.nfo"
    sfv_metadata_path = f"static/{filename}_sfv_metadata.txt"

    # Check if files exist
    if not (os.path.exists(release_info_path) and os.path.exists(filename_info_path)):
        return raw(b"Not found", status=404)

    with open(filename_info_path, 'r') as f:
        original_filename = f.read().strip()

    with open(release_info_path, 'r') as f:
        release_name = f.read().strip() or "release"
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add NFO if it exists
        if os.path.exists(nfo_data_path):
            zipf.write(nfo_data_path, arcname=original_filename)

        # Add SFVs if they exist
        if os.path.exists(sfv_metadata_path):
            with open(sfv_metadata_path, 'r') as f:
                for line in f:
                    parts = line.strip().split('|')
                    if len(parts) < 3:
                        continue
                    sfv_hexdig, sfvname, sfvpath = parts
                    sfv_data_path = f"static/{sfv_hexdig}.sfv"
                    if os.path.exists(sfv_data_path):
                        # Put SFV in subfolder if sfvpath is set
                        arc_name = sfvname if not sfvpath else os.path.join(sfvpath, sfvname)
                        zipf.write(sfv_data_path, arcname=arc_name)

    zip_buffer.seek(0)
    zip_data = zip_buffer.getvalue()

    # Return as raw binary data with correct headers
    return raw(
        zip_data, 
        headers={"Content-Disposition": f'attachment; filename="{release_name}.zip"'},
        content_type="application/zip"
    )


@app.route('/themes/<filename>')
async def serve_themes(request, filename):
    file_path = f'themes/{filename}'
    if os.path.exists(file_path):
        return await file(file_path)
    else:
        return HTTPResponse(status=404)
        
@app.route('/themes/svg/<filename>')
async def serve_svg_icons(request, filename):
    file_path = f'themes/svg/{filename}'
    if os.path.exists(file_path):
        return await file(file_path)
    else:
        return HTTPResponse(status=404)        

@app.route('/fonts/<filename>')
async def serve_fonts(request, filename):
    return await file(f'fonts/{filename}')

@app.route('/fonts/bootstrap/<filename>')
async def serve_bootstrap_fonts(request, filename):
    return await file(f'fonts/bootstrap/{filename}')    
    
@app.route('/static/<filename>')
async def serve_static(request, filename):
    return await file(f'static/{filename}')    

@app.route('/favicon.ico')
async def favicon(request):
    return await file('favicon.ico')
#-End of API stuff
#----------------------

# Cleanup files after NFO timeout.
# NOTE if you were to kill the process before this cleanup occurs, the files will remain in static.
# I use this as a way of easily testing without having to send new NFO data
def CleanupFiles(image_path, release_info_path, nfo_data_path, filename_info_path, saved_sfv_paths, saved_mi_paths, delay):
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
    mediainfo_fields_path = f"{os.path.splitext(image_path)[0]}_mediainfo.json"
    mi_metadata_path = f"{os.path.splitext(image_path)[0]}_mi_metadata.txt"    
    if os.path.exists(optional_fields_path):
        os.remove(optional_fields_path)
    if os.path.exists(sfv_metadata_path):
        os.remove(sfv_metadata_path)
    if os.path.exists(mediainfo_fields_path):
        os.remove(mediainfo_fields_path)
    if os.path.exists(mi_metadata_path):
        os.remove(mi_metadata_path)                
    for sfv in saved_sfv_paths:
        # Remove the SFV data file if it exists and is not None
        if sfv['sfv_data_path'] is not None and os.path.exists(sfv['sfv_data_path']):
            os.remove(sfv['sfv_data_path'])
        if os.path.exists(sfv['sfv_image_path']):
            os.remove(sfv['sfv_image_path'])
    for mi in saved_mi_paths:
        # Remove the mi data file if it exists and is not None
        if mi['mi_data_path'] is not None and os.path.exists(mi['mi_data_path']):
            os.remove(mi['mi_data_path'])


@app.middleware("request")
async def restrict_request_methods(request):
    # The only request types we need to support are GET and POST
    valid_request_types = ['GET', 'POST']
    
    if request.method not in valid_request_types:
        # Drop connection
        return HTTPResponse(status=500)

# Drop responses for bots scanning for services.
@app.exception(NotFound)
async def page_not_found(request, exception):
    return text("", status=500)

load_tokens()

if __name__ == '__main__':
    ssl_context = None
    if os.path.exists(le_certpath):
        ssl_context = le_certpath
        print("SSL Certificates found, running with SSL")
        sslFlag = True
    else:
        print("SSL Certificates not found, running without SSL")
        sslFlag = False

    app.run(debug=debug_mode, port=server_port, host=host_ip, ssl=ssl_context, access_log=debug_mode)
