import os
from dotenv import load_dotenv
from groq import Groq

# Charger les variables d'environnement
load_dotenv()

# Configurer le client Groq
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Test simple
response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[
        {
            "role": "system",
            "content": "Tu es un agent IA de Dealyze, spécialisé dans l'automatisation des deals."
        },
        {
            "role": "user",
            "content": "Dis bonjour et présente-toi."
        }
    ]
)

print("✅ Connexion Groq réussie")
print("Réponse:", response.choices[0].message.content)
