import os
import json
import io
import csv
import random
import shutil
from flask import (
    Flask, render_template, request, redirect, url_for,
    Response, jsonify, flash, session
)
from functools import wraps

app = Flask(__name__)
app.secret_key = "secret-key-123"  # Change ce secret en prod

DATA_DIR = "data"
TOURNAMENTS_DIR = os.path.join(DATA_DIR, "tournaments")
LOGO_PATH = "static/logo/logo.png"
os.makedirs(TOURNAMENTS_DIR, exist_ok=True)

# --- Sécurité ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash("Vous devez vous connecter pour accéder à cette page.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        # Modifie ici ton mot de passe
        if password == 'vNM#`E=@59~f3@%-Y3':
            session['logged_in'] = True
            flash("Connexion réussie.", "success")
            return redirect(url_for('index'))
        else:
            flash("Mot de passe incorrect.", "error")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash("Vous êtes déconnecté.", "success")
    return redirect(url_for('login'))

# --- Fonctions utilitaires ---

def safe_name(name):
    return "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in name)

def tournament_path(tournament_name, filename):
    safe_tname = safe_name(tournament_name)
    dir_path = os.path.join(TOURNAMENTS_DIR, safe_tname)
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, filename)

def save_tournament_data(tournament_name, filename, data):
    path = tournament_path(tournament_name, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

def load_tournament_data(tournament_name, filename, default=None):
    path = os.path.join(TOURNAMENTS_DIR, tournament_name, filename)
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        return json.load(f)
    if filename == "config.json":
        return {}
    return []

def list_tournaments():
    return sorted([d for d in os.listdir(TOURNAMENTS_DIR)
                   if os.path.isdir(os.path.join(TOURNAMENTS_DIR, d))])

@app.context_processor
def inject_globals():
    tournaments = list_tournaments()
    return dict(tournaments=tournaments, logo_exists=os.path.exists(LOGO_PATH))

@app.errorhandler(500)
def internal_error(error):
    flash("Une erreur interne est survenue, veuillez réessayer.", "error")
    return redirect(url_for("index"))

# --- Routes publiques ---

@app.route('/')
@login_required
def index():
    return render_template("index.html")

@app.route('/live_classement/<tournament_name>')
def live_classement(tournament_name):
    matches = load_tournament_data(tournament_name, "matches.json")
    config = load_tournament_data(tournament_name, "config.json")
    tables = int(config.get("tables", 1))
    scores = get_scores(tournament_name)
    next_matches = [m for m in matches if m["score1"] is None or m["score2"] is None]

    return render_template("classement_live.html",
                           scores=scores,
                           next_matches=next_matches[:tables],
                           tables=tables,
                           tournament_name=tournament_name)

# --- Routes protégées ---

@app.route('/create_tournament', methods=['POST'])
@login_required
def create_tournament():
    name = request.form.get('tournament_name')
    if not name:
        flash("Le nom du tournoi est obligatoire.", "error")
        return redirect(url_for("index"))

    safe_tname = safe_name(name)
    path = os.path.join(TOURNAMENTS_DIR, safe_tname)
    if os.path.exists(path):
        flash("Ce tournoi existe déjà.", "error")
        return redirect(url_for("index"))

    save_tournament_data(name, "players.json", [])
    save_tournament_data(name, "config.json", {
        "goals": 10,
        "rounds": 3,
        "mode": "doublette",
        "team_mode": "random",
        "avg_duration": 7,
        "tables": 1,
        "home_away_enabled": False
    })
    save_tournament_data(name, "matches.json", [])
    flash(f"Tournoi '{name}' créé avec succès.", "success")
    return redirect(url_for("start_tournament", tournament_name=safe_tname))

@app.route('/delete_tournament/<tournament_name>', methods=['POST'])
@login_required
def delete_tournament(tournament_name):
    path = os.path.join(TOURNAMENTS_DIR, tournament_name)
    if os.path.exists(path):
        shutil.rmtree(path)
        flash(f"Tournoi '{tournament_name}' supprimé.", "success")
    else:
        flash("Tournoi introuvable.", "error")
    return redirect(url_for("index"))

@app.route('/start/<tournament_name>')
@login_required
def start_tournament(tournament_name):
    players = load_tournament_data(tournament_name, "players.json", [])
    config = load_tournament_data(tournament_name, "config.json", {})

    # Calcul des rounds conseillés selon le mode
    if config.get("mode") == "doublette":
        suggested_rounds = (len(players) * 3) // 4
    else:
        suggested_rounds = (len(players) * 2) // 3

    return render_template(
        "start.html",
        tournament_name=tournament_name,
        players=players,
        config=config,
        suggested_rounds=suggested_rounds
    )

@app.route('/add_player/<tournament_name>', methods=['POST'])
@login_required
def add_player(tournament_name):
    name = request.form.get("name")
    players = load_tournament_data(tournament_name, "players.json")
    if name and name not in players:
        players.append(name)
        save_tournament_data(tournament_name, "players.json", players)
    return redirect(url_for("start_tournament", tournament_name=tournament_name))

@app.route('/remove_player/<tournament_name>/<name>', methods=['POST'])
@login_required
def remove_player(tournament_name, name):
    players = load_tournament_data(tournament_name, "players.json")
    if name in players:
        players.remove(name)
        save_tournament_data(tournament_name, "players.json", players)
    return redirect(url_for("start_tournament", tournament_name=tournament_name))

@app.route('/save_config/<tournament_name>', methods=['POST'])
@login_required
def save_config(tournament_name):
    try:
        players = load_tournament_data(tournament_name, "players.json", [])
        rounds = int(request.form.get('rounds', 3))
        mode = request.form.get('mode')

        # Calcul intelligent des rounds max
        if mode == "doublette":
            suggested_rounds = (len(players) * 3) // 4
        else:
            suggested_rounds = (len(players) * 2) // 3

        adjusted = False
        if rounds > suggested_rounds:
            rounds = suggested_rounds
            adjusted = True

        config = {
            'mode': mode,
            'rounds': rounds,
            'goals': int(request.form.get('goals', 10)),
            'team_mode': request.form.get('team_mode'),
            'avg_duration': int(request.form.get('match_time', 7)),
            'tables': int(request.form.get('num_tables', 1)),
            'points_win': int(request.form.get('points_win', 3)),
            'points_loss': int(request.form.get('points_loss', -1)),
            'home_away_enabled': request.form.get('home_away_enabled') == 'on',
            'adjusted_rounds': adjusted
        }

        save_tournament_data(tournament_name, "config.json", config)
        flash("Configuration sauvegardée.", "success")
        return redirect(url_for("start_tournament", tournament_name=tournament_name))
    except Exception as e:
        flash(f"Erreur de configuration: {e}", "error")
        return redirect(url_for("start_tournament", tournament_name=tournament_name))
@app.route('/generate_matches/<tournament_name>')
@login_required
def generate_matches(tournament_name):
    import itertools
    import random
    from collections import defaultdict

    players = load_tournament_data(tournament_name, "players.json")
    config = load_tournament_data(tournament_name, "config.json")
    players_count = len(players)
    mode = config.get("mode", "doublette")

    # Fonction pour équilibrer automatiquement les rounds
    def calculate_balanced_rounds(n, max_rounds=20):
        for r in range(max_rounds, 0, -1):
            if mode == "doublette" and (n * r) % 4 == 0:
                return r
            elif mode == "solo" and (n * r) % 2 == 0:
                return r
        return 1

    rounds = calculate_balanced_rounds(players_count)
    config["rounds"] = rounds
    config["adjusted_rounds"] = True
    save_tournament_data(tournament_name, "config.json", config)

    if mode == "doublette":
        if players_count % 2 != 0 or players_count < 4:
            flash("Le nombre de joueurs doit être pair et ≥ 4 pour le mode doublette.", "error")
            return redirect(url_for("start_tournament", tournament_name=tournament_name))
    elif mode != "solo":
        flash("❌ Mode de tournoi inconnu.", "error")
        return redirect(url_for("start_tournament", tournament_name=tournament_name))

    if players_count < 2:
        flash("Le nombre de joueurs doit être au moins 2.", "error")
        return redirect(url_for("start_tournament", tournament_name=tournament_name))

    matches = []
    player_match_count = {p: 0 for p in players}
    co_player_count = defaultdict(lambda: defaultdict(int))
    opponent_count = defaultdict(lambda: defaultdict(int))

    if mode == "solo":
        total_matches = (players_count * rounds) // 2
        attempts = 0
        max_attempts = 10000

        while len(matches) < total_matches and attempts < max_attempts:
            attempts += 1
            random.shuffle(players)
            for i in range(players_count):
                for j in range(i + 1, players_count):
                    p1, p2 = players[i], players[j]
                    if (
                        player_match_count[p1] < rounds and
                        player_match_count[p2] < rounds and
                        opponent_count[p1][p2] == 0
                    ):
                        matches.append({"team1": [p1], "team2": [p2], "score1": None, "score2": None})
                        player_match_count[p1] += 1
                        player_match_count[p2] += 1
                        opponent_count[p1][p2] += 1
                        opponent_count[p2][p1] += 1
                        break

        # Tentative forcée si joueurs en retard
        underplayed = [p for p, c in player_match_count.items() if c < rounds]
        force_attempts = 0
        while underplayed and force_attempts < 5000:
            force_attempts += 1
            random.shuffle(players)
            for i in range(players_count):
                for j in range(i + 1, players_count):
                    p1, p2 = players[i], players[j]
                    if player_match_count[p1] < rounds and player_match_count[p2] < rounds:
                        matches.append({"team1": [p1], "team2": [p2], "score1": None, "score2": None})
                        player_match_count[p1] += 1
                        player_match_count[p2] += 1
                        opponent_count[p1][p2] += 1
                        opponent_count[p2][p1] += 1
                        break
            underplayed = [p for p, c in player_match_count.items() if c < rounds]

    elif mode == "doublette":
        total_matches = (players_count * rounds) // 4
        attempts = 0
        max_attempts = 10000

        def can_play(p1, p2, p3, p4):
            team1 = [p1, p2]
            team2 = [p3, p4]
            all_players = team1 + team2
            if any(player_match_count[p] >= rounds for p in all_players):
                return False
            if any(co_player_count[a][b] > 0 for a, b in [(p1, p2), (p3, p4)]):
                return False
            if any(opponent_count[a][b] > 0 for a in team1 for b in team2):
                return False
            return True

        while len(matches) < total_matches and attempts < max_attempts:
            attempts += 1
            candidates = players[:]
            random.shuffle(candidates)
            p1, p2, p3, p4 = candidates[:4]

            if can_play(p1, p2, p3, p4):
                matches.append({"team1": [p1, p2], "team2": [p3, p4], "score1": None, "score2": None})
                for a, b in [(p1, p2), (p3, p4)]:
                    co_player_count[a][b] += 1
                    co_player_count[b][a] += 1
                for a in [p1, p2]:
                    for b in [p3, p4]:
                        opponent_count[a][b] += 1
                        opponent_count[b][a] += 1
                for p in [p1, p2, p3, p4]:
                    player_match_count[p] += 1

        # Forcer la main si nécessaire
        underplayed = [p for p, c in player_match_count.items() if c < rounds]
        force_attempts = 0
        while underplayed and force_attempts < 5000:
            force_attempts += 1
            random.shuffle(players)
            for i in range(players_count):
                for j in range(i + 1, players_count):
                    for k in range(players_count):
                        for l in range(k + 1, players_count):
                            team1 = [players[i], players[j]]
                            team2 = [players[k], players[l]]
                            all_players = set(team1 + team2)
                            if len(all_players) != 4:
                                continue
                            if any(player_match_count[p] >= rounds for p in all_players):
                                continue
                            matches.append({"team1": team1, "team2": team2, "score1": None, "score2": None})
                            for a, b in [(team1[0], team1[1]), (team2[0], team2[1])]:
                                co_player_count[a][b] += 1
                                co_player_count[b][a] += 1
                            for a in team1:
                                for b in team2:
                                    opponent_count[a][b] += 1
                                    opponent_count[b][a] += 1
                            for p in all_players:
                                player_match_count[p] += 1
                            break
            underplayed = [p for p, c in player_match_count.items() if c < rounds]

    save_tournament_data(tournament_name, "matches.json", matches)

    if any(c < rounds for c in player_match_count.values()):
        flash("⚠️ Tous les joueurs n'ont pas atteint le nombre de matchs souhaité.", "warning")
    else:
        flash("✅ Matchs générés avec succès.", "success")

    return redirect(url_for("show_matches", tournament_name=tournament_name))

@app.route('/matches/<tournament_name>')
@login_required
def show_matches(tournament_name):
    matches = load_tournament_data(tournament_name, "matches.json")
    config = load_tournament_data(tournament_name, "config.json")
    players = load_tournament_data(tournament_name, "players.json")
    rounds = config.get("rounds", 3)

    # Comptage des matchs par joueur
    match_count = {p: 0 for p in players}
    for match in matches:
        for p in match["team1"] + match["team2"]:
            match_count[p] += 1

    too_few = [p for p, c in match_count.items() if c < rounds]
    too_many = [p for p, c in match_count.items() if c > rounds]
    exact = [p for p, c in match_count.items() if c == rounds]

    return render_template(
        "matches.html",
        matches=matches,
        config=config,
        tournament_name=tournament_name,
        match_count=match_count,
        too_few=too_few,
        too_many=too_many,
        exact=exact
    )

@app.route('/classement/<tournament_name>')
@login_required
def classement(tournament_name):
    scores = get_scores(tournament_name)
    save_tournament_data(tournament_name, "scores.json", dict(scores))
    return render_template("classement.html", scores=scores, tournament_name=tournament_name)

@app.route('/export_csv/<tournament_name>')
@login_required
def export_scores_csv(tournament_name):
    scores = load_tournament_data(tournament_name, "scores.json")
    output = io.StringIO()
    # Ajout du BOM UTF-8 pour Excel
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Nom', 'Victoires', 'Défaites', 'Points'])
    for player, data in scores.items():
        writer.writerow([player, data.get('wins', 0), data.get('losses', 0), data.get('points', 0)])
    output.seek(0)
    return Response(output, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=classement_{tournament_name}.csv"})

@app.route('/export_results/<tournament_name>')
@login_required
def export_results(tournament_name):
    matches = load_tournament_data(tournament_name, "matches.json")
    scores = dict(get_scores(tournament_name))  # dict pour accès plus facile
    output = io.StringIO()
    # Ajout du BOM UTF-8 pour Excel
    output.write('\ufeff')
    writer = csv.writer(output)

    # Partie classement
    writer.writerow(["Classement"])
    writer.writerow(['Nom', 'Victoires', 'Défaites', 'Points'])
    for player, data in scores.items():
        writer.writerow([player, data.get('wins', 0), data.get('losses', 0), data.get('points', 0)])

    writer.writerow([])

    # Partie résultats des matchs
    writer.writerow(["Résultats des matchs"])
    writer.writerow(["Match n°", "Equipe 1", "Score 1", "Equipe 2", "Score 2"])
    for i, match in enumerate(matches, start=1):
        team1_str = " & ".join(match.get("team1", []))
        team2_str = " & ".join(match.get("team2", []))
        score1 = match.get("score1") if match.get("score1") is not None else ""
        score2 = match.get("score2") if match.get("score2") is not None else ""
        writer.writerow([i, team1_str, score1, team2_str, score2])

    output.seek(0)
    return Response(output, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=resultats_classement_{tournament_name}.csv"})

@app.route('/reset/<tournament_name>', methods=["POST"])
@login_required
def reset(tournament_name):
    path = os.path.join(TOURNAMENTS_DIR, tournament_name)
    if os.path.exists(path):
        shutil.rmtree(path)
    flash(f"Tournoi '{tournament_name}' réinitialisé.", "success")
    return redirect(url_for("index"))

@app.route('/end_tournament/<tournament_name>', methods=["POST"])
@login_required
def end_tournament(tournament_name):
    config = load_tournament_data(tournament_name, "config.json")
    config["finished"] = True
    save_tournament_data(tournament_name, "config.json", config)
    flash(f"Tournoi '{tournament_name}' terminé.", "success")
    return redirect(url_for("classement", tournament_name=tournament_name))

@app.route('/update_score/<tournament_name>', methods=['POST'])
@login_required
def update_score(tournament_name):
    data = request.get_json()
    index = data.get('index')
    team = data.get('team')
    score = data.get('score')

    matches = load_tournament_data(tournament_name, "matches.json")
    config = load_tournament_data(tournament_name, "config.json")
    goals = int(config.get("goals", 10))

    try:
        if team in ['score1', 'score2'] and 0 <= score <= goals:
            other_team = 'score2' if team == 'score1' else 'score1'
            other_score = matches[index].get(other_team)
            # Empêcher égalité
            if other_score is not None and other_score == score:
                return jsonify({"status": "error", "message": "Le score ne peut pas être égal."}), 400
            # Validation qu'une équipe ait au moins goals points
            if other_score is not None:
                if score < goals and other_score < goals:
                    return jsonify({"status": "error", "message": f"Au moins une équipe doit avoir au moins {goals} points."}), 400

            matches[index][team] = score
            save_tournament_data(tournament_name, "matches.json", matches)
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": "Score ou équipe invalide"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0")
