**NFO Sharing Daemon**
=====================================

**Overview**

This daemon provides a secure way to privately share NFO files with trusted groups. It's intended to be used in isolation from databases and other services.

**Important Notes**

* This project uses Flask, which is not intended for production use. However, it has been found to be suitable for its purpose.
* For optimal security and reliability, we recommend running the daemon in an isolated container.

**Getting Started**
-------------------

1. Configure global variables in `main.py` according to the comments provided.
2. To send an NFO file to the daemon, follow these steps:

### Sending an NFO File

* Send a POST request to `https://<host_address>:<host_port>/upload_nfo`
* Include an `Authorization` header with a valid token (see [Token Support](#token-support))
* The request body should contain the following JSON data:
```json
{
    "nfo_data": "<base64_encoded_data>", **REQUIRED**
    "release": "<release_name>", **REQUIRED**
    "filename": "<original_filename>", **REQUIRED**
    "save": true, **REQUIRED**
    "date": "<UTC_formatted_date>",
    "files": "<number_of_files>",
    "size": "<total_size_mb>"
}
```
* Required fields are marked with `REQUIRED` and must be included in the request.
* Optional fields can be omitted if not applicable.

### Response Format

The daemon will respond with a standard HTTP status code. Successful responses will include a JSON object with two values:

```json
{
    "message": "Success",
    "url": "/viewer/af76e15731ee2aa4a3c7a55afca4b8f8"
}
```
To link to the NFO file, construct the complete URL by concatenating `https://<host_address>:<host_port>` with the provided `url`.

### Favicon

If you wish to display a custom favicon, simply place it in the root folder. The daemon will automatically detect and serve it.

### Token Support

To generate tokens, use a tool like [Token Generator](https://it-tools.tech/token-generator) or run the included `generate_tokens.py` script. Add generated tokens to `tokens.txt`, one per line.
This is light token support intended for very basic usage, manage your tokens accordingly

**Acknowledgments**

* Font 'cp437_IBM_VGA8.ttf' is courtesy of the Ultimate Oldschool PC Font Pack (https://int10h.org/)
* Roboto fonts used in HTML output are licensed under the Apache License, Version 2.0 from Google Fonts.
