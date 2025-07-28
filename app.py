from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    print(">>> STARTSEITE geladen!")
    return "<h1>Hallo Welt!</h1>"

if __name__ == "__main__":
    app.run(debug=True)
