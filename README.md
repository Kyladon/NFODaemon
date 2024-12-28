
**SPRE NFO Daemon v2.x**
=====================================

**Overview**

This daemon provides a lightweight way to 'privately' share oldschool NFO files with others via HTTPS. It's intended to be used in isolation from databases and other services.\
With this, absolutely ZERO illegal files are being hosted. It's all metadata.
NFO content is sent to the daemon via a POST REST API request using an authorization token.\
\
The daemon will render the NFO text to PNG using a CP437 font, thus preserving the artistical aspects of the document. It can optionally allow users accessing the NFO to download, if permitted.\
By default, NFO's are only viewable up to 5 minutes after submission. The daemon then removes all associated files related to the submission.\
\
![image](https://github.com/user-attachments/assets/68bee1e6-df9f-4def-9304-89f318312721)

# Change Log
Version 2.x made some big changes, especially to the libraries being used.

## [2.1 Beta] - 2024-12-27
 
Complete changed the HTML template and added support for mediainfo.
 
### Added
- [REST ENDPOINT] New GET endpoint `/status` added to obtain the number of NFO's served and SSL expiry date
- [MEDIAINFO] New optional mediainfo array in the upload body that displays a new header on the viewer when used
- [.MEDIAINFO] Support for .mediainfo files to be shown after any SFV's
- [THEMES] Now supports bootstrap themes
- [EXAMPLES] Added examples folder that contains several JSON bodies to demostrate how it works
- [DOWNLOAD] Added button to download metadata package (Zip file that is the releasename containing nfo & sfv's including folders)
 
### Changed
- Flask has been replaced with Sanic & Jinja for better production-level request handling and templating
- SSL option now only needs to point to the folder containing the LetsEncrypt certificates


# REQUIREMENTS
-------------------
* Python 3.6 or later
* Lets Encrypt certificate (See [Getting Started](#getting-started))

## Important Notes

* Since 2.0, SPRE uses Sanic for managing requests and Jinja2 for HTML templating and bootstrap
* For optimal security and reliability, we recommend running the daemon in an isolated container. **DO NOT RUN AS ROOT**

## Getting Started
-------------------

1. Configure all the Config variables in `main.py` according to the comments provided.
2. Configure Certbot standalone to obtain the required pem files to operate as HTTPS. For more info on this see here: https://eff-certbot.readthedocs.io/en/stable/using.html#standalone 
Once done you should either copy the files to a folder accessable by this daemon or ensure the daemon can access the letsecrypt certificate path. Update the le_certpath in `main.py` 
4. To send an NFO file to the daemon, follow these steps:

## Sending a NFO File and (optionally) SFV file(s) / Mediainfo

* Send a POST request to `https://<host_address>:<host_port>/upload_nfo`
* Include an `Authorization` header with a valid token (see [Token Support](#token-support))
* Example request bodies are provided in the examples folder
* The request body should contain the following JSON data:
```json
{
    "nfo_data": "<base64_encoded_data>", **REQUIRED**
    "release": "<release_name>", **REQUIRED**
    "filename": "<original_filename>", **REQUIRED**
    "save": "<boolean>", **REQUIRED**
    "date": "<UTC_formatted_date>",
    "files": "<number_of_files>",
    "size": "<total_size_mb>",
    "section": "<section_name>"
    "sfvs": [    **OPTIONAL**
      {
        "sfv_data": "<base64_encoded_sfv_blob>", **REQUIRED**
        "sfvname": "release1.sfv",  **REQUIRED**
        "sfvpath": "cd1"  **OPTIONAL**
      },
      {
        "sfv_data": "base64_encoded_sfv_blob",  **REQUIRED**
        "sfvname": "release2.sfv",  **REQUIRED**
        "sfvpath": "cd2"  **OPTIONAL**
      }
    ],
    "mediainfos": [    **OPTIONAL**
      {
        "mi_data": "<base64_encoded_mediainfo_blob>", **REQUIRED**
        "sfvname": "file.mediainfo",  **REQUIRED**
        "sfvpath": ""  **OPTIONAL**
      },
      {
        "mi_data": "base64_encoded_mediainfo_blob",  **REQUIRED**
        "sfvname": "file2.media",  **REQUIRED**
        "sfvpath": ""  **OPTIONAL**
      }
    ],
	"mediainfo": [    **OPTIONAL**
	{
		"video": [ **REQUIRED (at least 1 track)**
		{
			"format": "<format_string>",
			"profile": <profile_string>",
			"level": "<level_string)",
			"bitrate": "<bitrate_bits_string>",
			"duration": "<duration_in_seconds_string>",
			"resolution": "<resolution_string>",
			"encode_library_name": "<encode_library_string>"
		}
		],
		"audio": [    **OPTIONAL**
		{
			"format": "<format_string>",
			"bitrate_mode": "<bitrate_mode_string>",
			"BitRate": "<bitrate_bits_string>",
			"channels": "<channels>",
			"language": "<language>"
		}
		],
		"text": [    **OPTIONAL**
		{
			"format": "<format_string>",
			"title": "<title_string>",
			"language": "<language_2_digit>",
			"forced": "<yes_no_string>"
		}
		]
	}
	]

}
```
* Required fields are marked with `REQUIRED` and must be included in the request.
* Optional fields can be omitted if not applicable.
* The sfvs array is optional, but if included there needs to be at least one entry with sfv_data and sfvname
* The Mediainfo array is optional, but if included there needs to be at least one video track

| Field       | Type     | Description                                                            |
| :---------- | :------: | :--------------------------------------------------------------------- |
|**nfo_data** | STRING   | entire blob base64 encoded.                                            |
|**release**  | STRING   | release name.                                                          |
|**filename** | STRING   | NFO original filename.                                                 |
|**save**     | BOOL     | true or false, to allow the user to download the original NFO or not.  |
|**date**     | STRING   | Format this however you like as there is no datetime conversion done server side. Suggest sending UTC formatted date like 2005-05-28 17:58:07.|
|**files**    | INT      | Total number of files in release.                                     |
|**size**     | FLOAT    | Size of release in mb's.                                              |
|**section**  | STRING   | Name of the section the release resides in                            |
|**sfv_data** | STRING   | entire SFV blob base64 encoded.                                       |
|**sfvname**  | STRING   | SFV original filename                                                 |
|**sfvpath**  | STRING   | Path to SFV file in case more than one, EG CD1/ CD2/ etc..            |
|**mi_data** | STRING    | entire .MEDIAINFO blob base64 encoded.                                |
|**miname**  | STRING    | mediainfo original filename                                           |
|**mipath**  | STRING    | Path to mediainfo file in case more than one, oldschool video...      |

#### Optional Mediainfo section
##### This is seperate to the mediainfo blob, and is used only to show extra details on the sidebar if desired.
If the mediainfo array is present then it must contain at least 1 video track, everything else is optional. All fields however are optional
| VIDEO                   | Type     | Description                                                            |
| :---------------------- | :------: | :--------------------------------------------------------------------- |
|**format**               | STRING   | Video format, E.G: HEVC                                                |
|**profile**              | STRING   | Encoding profile, E.G Main                                             |
|**level**                | STRING   | Level, E.G: 5.1                                                        |
|**bitrate**              | STRING   | Bitrate in bits, will be displayed as kb/s                             |
|**duration**             | STRING   | Duration in seconds, will be displayed as minutes                      |
|**resolution**           | STRING   | Resolution, E.G: 1920x1080                                             |
|**enclode_library_name** | STRING   | Encoding library, E.G: x265                                            |

| AUDIO                   | Type     | Description                                                            |
| :---------------------- | :------: | :--------------------------------------------------------------------- |
|**format**               | STRING   | Audio format, E.G: DTS                                                 |
|**bitrate_mode**         | STRING   | Bitrate mode, E.G: VBR                                                 |
|**bitrate**              | STRING   | Bitrate in bits, will be displayed as kb/s                             |
|**channels**             | STRING   | Number of channels                                                     |
|**language**             | STRING   | 2 Digit language ID                                                    |

| TEXT                    | Type     | Description                                                            |
| :---------------------- | :------: | :--------------------------------------------------------------------- |
|**format**               | STRING   | Subtitle format, E.G: UTF-8 or PGS                                     |
|**title**                | STRING   | Language title, E.G English                                            |
|**language**             | STRING   | 2 Digit language ID                                                    |
|**forced**               | STRING   | Are the subtitles forced Yes/No?                                       |

##### Example output with mediainfo
![image](https://github.com/user-attachments/assets/eb4f2c2e-6bb0-4ec5-92c0-dc539ce6731b)


### Response Format

The daemon will respond with a standard HTTP status code. A successful 200 response will include a JSON object with two values:

```json
{
    "message": "Success",
    "url": "/viewer/af76e15731ee2aa4a3c7a55afca4b8f8"
}
```
To link to the NFO file, construct the complete URL by concatenating `https://<host_address>:<host_port>` with the provided `url`.

## Daemon Status GET request
You can now request some basic status information.
* Send a GET request to `https://<host_address>:<host_port>/status`
This will require an authorisation token

### Response Format
The status, if succesfull will return a 200 status along with a JSON body
```json
{
    "nfoServed": 1234,
    "sslExpiry": "2025-03-19"
}
```
This very simply provides a count of the succesfull POST requests to upload_nfo.
It also includes the sslExpiry (if SSL is in use) of your lets encrypt cert which can trigger another process to restart the daemon to pick up updated certs if required.


### HTML Themes

SPRE now uses bootstrap themes to colour the viewer. Simply ensure you have a bootstrap.min.css and bootstrap.min.css.map inside the /themes folder.
The example provided is the Darkly theme from https://bootswatch.com
Ensure you keep the javascript files in the themes folder as this ensures that bootstrap operates entirely locally to the daemon with no external linking.

Obviously you'll need a dark theme to keep in line with the white-on-black NFO rendering.

##### Important Note
Bootstrap themes often link to external fonts, usually something like `https://fonts.googleapis.com/css2?family=Lato:ital,wght@0,400;0,700;1,400&display=swap`
If you want to avoid any external requests like this simply take the response from that URL and save it to /fonts/bootstrap/font.css
Download the fonts listed in font.css and place them into the same folder, then edit the URL's to point to them.
The theme this daemon comes with has already handled this so you can see what I did as an example.

### Favicon

If you wish to display a custom favicon, simply place it in the root folder. The daemon will automatically detect and serve it.

### Token Support

To generate tokens, use a tool like [Token Generator](https://it-tools.tech/token-generator) or run the included `generate_tokens.py` script. Add generated tokens to `tokens.txt`, one per line.
This is light token support intended for very basic usage, manage your tokens accordingly

**Acknowledgments**

* Font 'cp437_IBM_VGA8.ttf' is courtesy of the Ultimate Oldschool PC Font Pack (https://int10h.org/)
* Roboto fonts used in HTML output are licensed under the Apache License, Version 2.0 from Google Fonts.
