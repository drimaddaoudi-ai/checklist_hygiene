import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta, timezone
import json

# --- CONFIGURATION ---
st.set_page_config(page_title="Checklist Hygiène", page_icon="🏥", layout="centered")

# --- PARAMÈTRES TECHNIQUES (quota / perf) ---
CACHE_TTL_SECONDS = 30
LIMIT_JOURNAL_FEED = 20
LIMIT_HISTORY = 50

# --- DONNÉES DE CONFIGURATION ---
ADMIN_USER = "admin"

ROOMS_ENFANT = ["Salle A", "Salle B", "Salle C", "Salle D", "Salle E"]
ROOMS_FEMME = ["Salle F", "Salle G", "Salle H", "Salle I", "Salle J"]

# --- CHECKLISTS (Contenu Intouché) ---
CHECKLIST_ITEMS_ROOM = [
    "1. Solutions hydroalcooliques présentes",
    "2. Solutions hydroalcooliques remplies",
    "3. Boite de gants propre présente",
    "4. Moniteur fonctionnel avec câble en charge (prise ondulée)",
    "5. Multimed du moniteur présent et fonctionnel",
    "6. Respirateur fonctionnel avec câble en charge (prise ondulée)",
    "7. Système d'aspiration présent (bocal, tuyau, manomètre)",
    "8. Système d'aspiration propre (si non : changé par un propre)",
    "9. Système d'aspiration fonctionnel",
    "10. Barboteur d'oxygène branché et fonctionnel",
    "11. Réanima (BAVU) adapté à la taille du patient présent",
    "12. Masque facial adapté à la taille du patient présent",
    "13. Lit fonctionnel avec câble branchée (prise ondulée)",
    "14. Matelas anti escarre présent",
    "15. Moteur du matelas fonctionnel avec câble branché",
    "16. Environnement du malade propre et rangé"
]

ISOLEMENT_ITEMS = [
    "Chariot d'isolement présent",
    "Surblouses présentes et quantité suffisante",
    "Boite de masque chirurgical présente",
    "Calots présents",
    "Solution hydroalcoolique sur le chariot",
    "Boite de gants propres sur le chariot"
]

CHECKLIST_ITEMS_HALL = [
    "Solution hydroalcoolique présente à l'entrée du secteur",
    "Solution hydroalcoolique présente à la réception",
    "Réception rangée et organisée"
]

CHECKLIST_ITEMS_LAVABO = [
    "Lavabo propre et non encombré",
    "Savon disponible et rempli",
    "Robinet fonctionnel",
    "Papiers essuie-main disponibles"
]

# --- CONNEXION FIREBASE ---
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        try:
            # 1. Essayer de charger depuis les SECRETS Streamlit (Cloud)
            if "textkey" in st.secrets:
                key_dict = json.loads(st.secrets["textkey"])
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            
            # 2. Sinon, essayer de charger le fichier LOCAL (PC)
            else:
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
                
        except Exception as e:
            st.error(f"Erreur de connexion Firebase : {e}")
            st.stop()
            
    return firestore.client()

try:
    db = get_db()
except Exception as e:
    st.error(f"Erreur DB : {e}")
    st.stop()

# --- OUTILS CACHE LOCAL LECTURE ---

def _get_refresh_token(collection_name: str) -> int:
    return st.session_state.get(f"_refresh_token_{collection_name}", 0)

def _bump_refresh_token(collection_name: str):
    key = f"_refresh_token_{collection_name}"
    st.session_state[key] = st.session_state.get(key, 0) + 1

    # Invalidation cache local de cette collection
    prefix = f"_cache_{collection_name}_"
    keys_to_delete = [k for k in st.session_state.keys() if k.startswith(prefix)]
    for k in keys_to_delete:
        del st.session_state[k]

def _cache_key(collection_name: str, limit: int) -> str:
    return f"_cache_{collection_name}_{limit}"

# --- FONCTIONS LOGIQUE MÉTIER ---

def delete_document(collection, doc_id):
    try:
        db.collection(collection).document(doc_id).delete()
        _bump_refresh_token(collection)
    except Exception as e:
        st.error(f"Erreur suppression ({collection}) : {e}")

def can_manage_entry(entry_user, entry_timestamp):
    current_user = st.session_state.get("user")
    if current_user == ADMIN_USER:
        return True

    if current_user == entry_user and entry_timestamp:
        try:
            now = datetime.now(timezone.utc)
            entry_date = entry_timestamp

            # Protection si timestamp sans tzinfo
            if getattr(entry_date, "tzinfo", None) is None:
                entry_date = entry_date.replace(tzinfo=timezone.utc)

            diff = now - entry_date
            if diff < timedelta(hours=24):
                return True
        except Exception:
            return False

    return False

# --- FONCTIONS CRUD OPTIMISÉES ---

def add_checklist_entry(user, type_checklist, service, salle, taches_ok, taches_nok, obs):
    """Enregistre les tâches faites ET non faites"""
    now_local = datetime.now()
    date_now = now_local.strftime("%Y-%m-%d")
    heure_now = now_local.strftime("%H:%M:%S")

    data = {
        "user": user,
        "date": date_now,
        "heure": heure_now,
        "poste": type_checklist,
        "service": service,
        "salle": salle,
        "taches_ok": ", ".join(taches_ok),    # Ce qui est validé (Vert)
        "taches_nok": ", ".join(taches_nok),  # Ce qui n'est pas validé (Rouge)
        "nb_taches": len(taches_ok),
        "total_items": len(taches_ok) + len(taches_nok),
        "observation": obs,
        "timestamp": firestore.SERVER_TIMESTAMP
    }
    try:
        db.collection("checklists").add(data)
        _bump_refresh_token("checklists")
    except Exception as e:
        st.error(f"Erreur enregistrement checklist : {e}")

def add_journal_entry(user, message):
    now_local = datetime.now()
    date_now = now_local.strftime("%Y-%m-%d")
    heure_now = now_local.strftime("%H:%M:%S")

    data = {
        "user": user,
        "date": date_now,
        "heure": heure_now,
        "message": message,
        "timestamp": firestore.SERVER_TIMESTAMP
    }
    try:
        db.collection("journal").add(data)
        _bump_refresh_token("journal")
    except Exception as e:
        st.error(f"Erreur enregistrement journal : {e}")

def get_data_with_ids(collection_name, limit=20):
    """
    OPTIMISATION QUOTA :
    - cache local (session) avec TTL
    - invalidation auto après add/delete
    """
    ck = _cache_key(collection_name, limit)
    now_utc = datetime.now(timezone.utc)
    refresh_token = _get_refresh_token(collection_name)

    cached = st.session_state.get(ck)
    if cached:
        age = (now_utc - cached["fetched_at"]).total_seconds()
        if cached["refresh_token"] == refresh_token and age < CACHE_TTL_SECONDS:
            return cached["data"]

    try:
        docs = (
            db.collection(collection_name)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )

        items = []
        for doc in docs:
            item = doc.to_dict()
            item["id"] = doc.id
            items.append(item)

        st.session_state[ck] = {
            "data": items,
            "fetched_at": now_utc,
            "refresh_token": refresh_token
        }
        return items
    except Exception as e:
        st.error(f"Erreur lecture {collection_name} : {e}")
        return []

# --- AUTHENTIFICATION ---
def check_login_db(username, password_input):
    try:
        doc_ref = db.collection("utilisateurs").document(username)
        doc = doc_ref.get()
        if doc.exists:
            user_data = doc.to_dict()
            if user_data.get("password") == password_input:
                return True
    except Exception:
        return False
    return False

def login():
    st.title("🏥 Hygiène & Contrôle")
    with st.form("login_form"):
        username = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Se connecter"):
            if check_login_db(username, password):
                st.session_state["logged_in"] = True
                st.session_state["user"] = username
                st.success("Connexion...")
                st.rerun()
            else:
                st.error("Erreur d'identifiants")

# --- APPLICATION ---
def main_app():
    # Sidebar
    st.sidebar.title(f"👤 {st.session_state['user']}")
    if st.session_state["user"] == ADMIN_USER:
        st.sidebar.markdown("BADGE: 🛡️ **Super Admin**")

    if st.sidebar.button("Déconnexion"):
        st.session_state["logged_in"] = False
        st.session_state.pop("user", None)
        st.rerun()

    menu = st.sidebar.radio("Menu", ["📝 Nouvelle Checklist", "📒 Journal", "⚙️ Gestion & Historique"])

    # --- 1. CHECKLIST ---
    if menu == "📝 Nouvelle Checklist":
        st.header("Nouvelle Checklist Hygiène")

        type_checklist = st.selectbox(
            "Type de checklist",
            ["Matin", "Après-midi", "Désinfection matériel", "Désinfection respi", "Désinfection salle"]
        )

        # LOGIQUE SECTEURS (Matin / Après-midi)
        if type_checklist in ["Matin", "Après-midi"]:

            secteur = st.selectbox("Secteur", ["Réa Enfant", "Réa Femme"], key="secteur_selector")

            # Init Session State
            if "current_rooms_status" not in st.session_state or st.session_state.get("current_sector_name") != secteur:
                st.session_state["current_sector_name"] = secteur
                if secteur == "Réa Enfant":
                    items_to_check = ROOMS_ENFANT + ["Hall", "Lavabo 1", "Lavabo 2"]
                else:  # Réa Femme
                    items_to_check = ROOMS_FEMME + ["Hall", "Lavabo 3", "Lavabo 4"]
                st.session_state["current_rooms_status"] = {item: False for item in items_to_check}

            rooms_status = st.session_state["current_rooms_status"]

            st.warning("⚠️ Merci de cocher l'état de chaque élément (Oui/Non/Non Applicable).")

            # Barre de progression simplifiée
            st.write("Progression :")
            cols = st.columns(len(rooms_status))
            for i, (room_name, is_done) in enumerate(rooms_status.items()):
                with cols[i]:
                    color = "✅" if is_done else "⏳"
                    st.caption(f"{color} {room_name}")

            st.divider()

            # Sélection Zone
            salle_active = st.radio("Zone à contrôler :", list(rooms_status.keys()), horizontal=True)

            if rooms_status[salle_active]:
                st.success(f"✅ Checklist validée pour **{salle_active}**.")
            else:
                st.markdown(f"### 🩺 Contrôle : {salle_active}")

                # --- LOGIQUE DE CALCUL DES ITEMS ---
                theoretical_items = []

                # 1. Gestion Isolement (Hors Form)
                isolement_active = False
                if salle_active.startswith("Salle"):
                    if st.checkbox("⚠️ Salle en isolement ?", key=f"iso_{salle_active}"):
                        isolement_active = True

                # 2. Construction de la liste théorique
                if salle_active.startswith("Salle"):
                    theoretical_items = list(CHECKLIST_ITEMS_ROOM)
                    if isolement_active:
                        iso_items_formatted = [f"[ISOLEMENT] {i}" for i in ISOLEMENT_ITEMS]
                        theoretical_items.extend(iso_items_formatted)

                elif salle_active == "Hall":
                    theoretical_items = list(CHECKLIST_ITEMS_HALL)
                elif salle_active.startswith("Lavabo"):
                    theoretical_items = list(CHECKLIST_ITEMS_LAVABO)

                # --- FORMULAIRE ---
                with st.form(f"form_{salle_active}"):
                    
                    # On prépare les listes pour le stockage
                    current_ok = []
                    current_nok = []

                    st.write("**Veuillez renseigner chaque point :**")

                    for idx, item in enumerate(theoretical_items):
                        st.markdown(f"**{item}**")
                        # Boutons Radio : Oui / Non / N/A
                        # Index=None oblige l'utilisateur à choisir (pas de valeur par défaut)
                        choice = st.radio(
                            label=f"Choix pour {item}",
                            options=["Oui", "Non", "N/A"],
                            horizontal=True,
                            key=f"rad_{salle_active}_{idx}",
                            label_visibility="collapsed",
                            index=None 
                        )
                        
                        # Logique de tri
                        if choice == "Oui":
                            current_ok.append(item)
                        elif choice == "N/A":
                            current_ok.append(f"{item} (N/A)") # Compté comme Validé
                        elif choice == "Non":
                            current_nok.append(item) # Compté comme Non Validé
                        else:
                            # Si l'utilisateur ne coche rien (None), on le considère comme Manquant/NOK
                            current_nok.append(f"{item} (Non renseigné)")

                    # Cas spécial : Si salle et PAS isolement, note auto
                    if salle_active.startswith("Salle") and not isolement_active:
                        current_ok.append("Pas d'isolement (Auto)")

                    st.markdown("---")
                    obs_salle = st.text_input("Observation (Optionnel)")

                    if st.form_submit_button(f"Valider {salle_active}", type="primary"):

                        # Sauvegarde
                        add_checklist_entry(
                            user=st.session_state["user"],
                            type_checklist=type_checklist,
                            service=secteur,
                            salle=salle_active,
                            taches_ok=current_ok,
                            taches_nok=current_nok,
                            obs=obs_salle
                        )

                        st.session_state["current_rooms_status"][salle_active] = True
                        st.rerun()

            # Fin du secteur
            if all(rooms_status.values()):
                st.balloons()
                st.success(f"🎉 Secteur {secteur} terminé !")
                if st.button("Nouveau secteur"):
                    del st.session_state["current_rooms_status"]
                    st.rerun()

        else:
            # Autres checklists simples
            st.info("Checklist standard")
            with st.form("simple_check"):
                taches = ["Désinfection effectuée", "Matériel rangé"]
                checked = [t for t in taches if st.checkbox(t)]
                unchecked = [t for t in taches if t not in checked]

                obs = st.text_input("Observation")
                if st.form_submit_button("Valider"):
                    add_checklist_entry(st.session_state["user"], type_checklist, "Autre", "N/A", checked, unchecked, obs)
                    st.success("Enregistré")

    # --- 2. JOURNAL ---
    elif menu == "📒 Journal":
        st.header("Journal de Service")
        with st.form("journal_add"):
            msg = st.text_area("Observation")
            if st.form_submit_button("Ajouter"):
                add_journal_entry(st.session_state["user"], msg)
                st.success("Ajouté")

        st.divider()
        st.subheader("Fil d'actualité")
        items = get_data_with_ids("journal", limit=LIMIT_JOURNAL_FEED)
        for item in items:
            st.info(f"**{item.get('user')}** ({item.get('date')} {item.get('heure')}):\n\n{item.get('message')}")

    # --- 3. GESTION ---
    elif menu == "⚙️ Gestion & Historique":
        st.header("Historique & Gestion")

        tab_check, tab_journ = st.tabs(["📋 Checklists", "📒 Journal"])

        with tab_check:
            items_c = get_data_with_ids("checklists", limit=LIMIT_HISTORY)

            if items_c:
                df_export = pd.DataFrame(items_c).drop(columns=["id", "timestamp"], errors="ignore")
                st.download_button(
                    "📥 Télécharger (50 derniers)",
                    df_export.to_csv(index=False).encode("utf-8"),
                    "checklists.csv",
                    "text/csv"
                )

            st.caption("Affichage des 50 dernières fiches.")

            for item in items_c:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        salle_info = f" | 📍 {item.get('salle')}" if item.get("salle") else ""
                        st.markdown(f"**{item.get('date')} - {item.get('heure')}** | 👤 {item.get('user')}")
                        st.caption(f"Type : {item.get('poste')} | Secteur : {item.get('service')}{salle_info}")

                        if item.get("observation"):
                            st.warning(f"📝 Note : {item.get('observation')}")

                        # AFFICHAGE VERT / ROUGE
                        with st.expander("Voir détails Conformité"):
                            t_ok = item.get("taches_ok", item.get("taches", ""))
                            t_nok = item.get("taches_nok", "")

                            if t_ok:
                                st.success(f"✅ **Validé :**\n\n{t_ok}")

                            if t_nok:
                                st.error(f"❌ **NON Validé / Manquant :**\n\n{t_nok}")
                            elif not t_ok and not t_nok:
                                st.info(f"Détails : {item.get('taches')}")

                    with c2:
                        ts = item.get("timestamp")
                        if can_manage_entry(item.get("user"), ts):
                            if st.button("🗑️", key=f"del_c_{item['id']}", type="primary"):
                                delete_document("checklists", item["id"])
                                st.rerun()
                        else:
                            st.caption("🔒")

        with tab_journ:
            items_j = get_data_with_ids("journal", limit=LIMIT_HISTORY)
            if items_j:
                df_export_j = pd.DataFrame(items_j).drop(columns=["id", "timestamp"], errors="ignore")
                st.download_button(
                    "📥 Télécharger Journal",
                    df_export_j.to_csv(index=False).encode("utf-8"),
                    "journal.csv",
                    "text/csv"
                )

            for item in items_j:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.markdown(f"**{item.get('date')}** | 👤 {item.get('user')}")
                        st.info(item.get("message"))
                    with c2:
                        ts = item.get("timestamp")
                        if can_manage_entry(item.get("user"), ts):
                            if st.button("🗑️", key=f"del_j_{item['id']}", type="primary"):
                                delete_document("journal", item["id"])
                                st.rerun()

# --- LANCEMENT ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if st.session_state["logged_in"]:
    main_app()
else:
    login()
