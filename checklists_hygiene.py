import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Checkliste Hygiène", page_icon="🏥", layout="centered")

# --- CONNEXION FIREBASE (Gérée via st.secrets pour la sécurité) ---
# Cette fonction est mise en cache pour ne pas se reconnecter à chaque clic
@st.cache_resource
def get_db():
    # On vérifie si l'app Firebase est déjà initialisée
    if not firebase_admin._apps:
        # On récupère les infos du fichier JSON stocké dans les secrets Streamlit
        key_dict = json.loads(st.secrets["textkey"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

try:
    db = get_db()
except Exception as e:
    st.error(f"Erreur de connexion à la base de données : {e}")
    st.stop()

# --- FONCTIONS CRUD (Create, Read) ---

def add_checklist_entry(user, poste, taches_cochees, service):
    date_now = datetime.now().strftime("%Y-%m-%d")
    heure_now = datetime.now().strftime("%H:%M:%S")
    
    data = {
        "user": user,
        "date": date_now,
        "heure": heure_now,
        "poste": poste,
        "service": service,
        "taches": ", ".join(taches_cochees), # On stocke la liste comme une phrase
        "nb_taches": len(taches_cochees),
        "timestamp": firestore.SERVER_TIMESTAMP # Pour trier facilement
    }
    # Ajout dans la collection 'checklists'
    db.collection("checklists").add(data)

def add_journal_entry(user, message):
    date_now = datetime.now().strftime("%Y-%m-%d")
    heure_now = datetime.now().strftime("%H:%M:%S")
    
    data = {
        "user": user,
        "date": date_now,
        "heure": heure_now,
        "message": message,
        "timestamp": firestore.SERVER_TIMESTAMP
    }
    db.collection("journal").add(data)

def get_data_as_dataframe(collection_name):
    # Récupérer tous les documents
    docs = db.collection(collection_name).order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    
    # Convertir en liste de dictionnaires
    items = []
    for doc in docs:
        item = doc.to_dict()
        # On enlève l'objet timestamp brut pour l'affichage propre
        if 'timestamp' in item:
            del item['timestamp']
        items.append(item)
    
    return pd.DataFrame(items)

# --- AUTHENTIFICATION ---
USERS = {
    "vice_major": "admin123",  # A changer
    "as_hygiene_matin": "matin01",
    "as_hygiene_soir": "soir01",
    "surveillante": "chef2026"
}

def login():
    st.title("🏥 Hygiène & Contrôle")
    st.markdown("### Authentification")
    
    with st.form("login_form"):
        username = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")
        submit = st.form_submit_button("Se connecter")
        
        if submit:
            if username in USERS and USERS[username] == password:
                st.session_state["logged_in"] = True
                st.session_state["user"] = username
                st.success("Connexion réussie")
                st.rerun()
            else:
                st.error("Identifiant ou mot de passe incorrect")

# --- APPLICATION PRINCIPALE ---
def main_app():
    st.sidebar.success(f"Connecté : {st.session_state['user'].upper()}")
    
    if st.sidebar.button("Déconnexion"):
        st.session_state["logged_in"] = False
        st.rerun()

    menu = st.sidebar.radio("Menu", ["📝 Remplir Checkliste", "📒 Journal de Service", "📊 Historique & Export"])

    # --- TAB 1 : REMPLIR ---
    if menu == "📝 Remplir Checkliste":
        st.header("Nouvelle Checkliste")
        
        col1, col2 = st.columns(2)
        with col1:
            poste = st.selectbox("Moment / Poste", ["Démarrage Matin", "Tour de 14h", "Fin de journée", "Nettoyage Approfondi"])
        with col2:
            service = st.selectbox("Secteur", ["Réa Mère", "Réa Enfant", "Bloc", "Salle de réveil"])

        taches_possibles = [
            "Niveau des solutions hydro-alcooliques vérifié",
            "Poubelles DASRI vidées et fermées",
            "Stock EPI (Gants/Masques) complété",
            "Surfaces hautes dépoussiérées",
            "Poignées de portes désinfectées",
            "Chariots de soins nettoyés",
            "Traçabilité Frigo complétée",
            "Lavabos : pas d'encombrement"
        ]
        
        st.write("---")
        with st.form("check_form"):
            st.write("**Cochez les actions réalisées :**")
            checked = []
            for t in taches_possibles:
                if st.checkbox(t):
                    checked.append(t)
            
            obs_rapide = st.text_input("Observation rapide (optionnel)")
            
            submitted = st.form_submit_button("Valider et Enregistrer", use_container_width=True)
            
            if submitted:
                if checked:
                    add_checklist_entry(st.session_state['user'], poste, checked, service)
                    if obs_rapide:
                        add_journal_entry(st.session_state['user'], f"[Via Checkliste] {obs_rapide}")
                    st.balloons()
                    st.success("✅ Données envoyées vers le Cloud !")
                else:
                    st.warning("Veuillez cocher au moins une case.")

    # --- TAB 2 : JOURNAL ---
    elif menu == "📒 Journal de Service":
        st.header("Cahier de transmission")
        
        with st.form("journal_form"):
            message = st.text_area("Observation / Incident / Besoin", height=100)
            submit_msg = st.form_submit_button("Ajouter au journal")
            
            if submit_msg and message:
                add_journal_entry(st.session_state['user'], message)
                st.success("Note ajoutée.")

        st.subheader("Fil d'actualité")
        df_journal = get_data_as_dataframe("journal")
        if not df_journal.empty:
            for index, row in df_journal.iterrows():
                st.info(f"📅 {row['date']} à {row['heure']} | 👤 {row['user']}\n\n{row['message']}")
        else:
            st.write("Aucune observation.")

    # --- TAB 3 : HISTORIQUE ---
    elif menu == "📊 Historique & Export":
        st.header("Base de données Hygiène")
        
        tab_check, tab_journ = st.tabs(["Checklistes", "Journal"])
        
        with tab_check:
            df_checks = get_data_as_dataframe("checklists")
            st.dataframe(df_checks, use_container_width=True)
            
            # BOUTON DOWNLOAD
            csv = df_checks.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Télécharger l'historique Checklistes (CSV)",
                csv,
                "historique_checklists.csv",
                "text/csv",
                key='download-csv'
            )

        with tab_journ:
            df_journ = get_data_as_dataframe("journal")
            st.dataframe(df_journ, use_container_width=True)
            
            csv_j = df_journ.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Télécharger le Journal (CSV)",
                csv_j,
                "historique_journal.csv",
                "text/csv",
                key='download-journal'
            )

# --- GESTION ÉTAT ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if st.session_state["logged_in"]:
    main_app()
else:
    login()