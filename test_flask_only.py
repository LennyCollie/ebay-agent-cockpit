print("1", flush=True)
from flask import Flask
print("2", flush=True)
app = Flask(__name__)
print("3", flush=True)
