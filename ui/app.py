
from flask import Flask, render_template, send_from_directory

app = Flask(__name__, template_folder="templates")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory("templates", filename)


if __name__ == "__main__":
    app.run(debug=True)
