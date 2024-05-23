import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
import datetime
import json
import os
from babel.dates import format_date, format_timedelta

# Configuration du Bot
TOKEN = 'YOUT TOKEN BOT'  # Remplacez par votre token de bot
LOG_FILE = 'service_log.txt'
DATA_FILE = 'service_data.json'
ALERT_CHANNEL_ID = 1242869272221585468  # Remplacez par l'ID de votre salon textuel d'alertes
STATS_CHANNEL_ID = 1242888180999651328  # Remplacez par l'ID de votre salon textuel dédié aux statistiques
MODERATOR_ROLE_NAMES = ["Administrateur", "Patron", "Co-Patron", "DRH", "RH", "Ingénieur informatique"]  # Liste des noms des rôles de modérateur
EN_SERVICE_ROLE_NAME = "En Service"  # Remplacez par le nom du rôle "En Service" sur votre serveur
TOTAL_EFFECTIF_CHANNEL_ID = 1242870853834768476  # Remplacez par l'ID de votre canal vocal "Effectif Total"
EN_SERVICE_CHANNEL_ID = 1242870790379012248  # Remplacez par l'ID de votre canal vocal "En Service"

# Mapping des rôles Discord aux rôles de pointage
DISCORD_TO_POINTAGE_ROLE = {
    'Recrue 2': 'r2',
    'Recrue 1': 'r1',
    'Confirmer 2': 'c2',
    'Confirmer 1': 'c1',
    'Expérimenter 2': 'exp2',
    'Expérimenter 1': 'exp1',
    'Chef déquipe': 'ce',
    'DRH': 'drh',
    'RH': 'rh',
    'Co-Patron': 'copatron',
    'Patron': 'patron'
}

HOURLY_RATE = {
    'r2': 50000,
    'r1': 60000,
    'c2': 75000,
    'c1': 80000,
    'exp2': 90000,
    'exp1': 95000,
    'ce': 105000,
    'drh': 0,
    'rh': 0,
    'copatron': 0,
    'patron': 0
}

# Variables pour les heures de service autorisées
week_start_time = datetime.time(18, 0)
week_end_time = datetime.time(1, 0)
weekend_start_time = datetime.time(18, 0)
weekend_end_time = datetime.time(2, 0)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

service_start_times = {}
cumulative_service_durations = {}
service_roles = {}
status_message_id = None  # ID du message de statut pour le mettre à jour

def log_service(member, action, role=None, total_hours=None, salary=None):
    with open(LOG_FILE, 'a') as f:
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if action == "start":
            f.write(f"{timestamp} - {member.name}#{member.discriminator} ({member.id}) a commencé son service en tant que {role}\n")
        elif action == "end":
            f.write(f"{timestamp} - {member.name}#{member.discriminator} ({member.id}) a terminé son service\n")
            if total_hours is not None and salary is not None:
                f.write(f"  Total en service: {total_hours} heures\n")
                f.write(f"  Salaire: ${salary:,.2f}\n")

def save_data():
    data = {
        'service_start_times': {k: {'time': v['time'].isoformat()} for k, v in service_start_times.items()},
        'cumulative_service_durations': {k: v.total_seconds() for k, v in cumulative_service_durations.items()},
        'service_roles': service_roles
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            global service_start_times, cumulative_service_durations, service_roles
            service_start_times = {int(k): {'time': datetime.datetime.fromisoformat(v['time'])} for k, v in data['service_start_times'].items()}
            cumulative_service_durations = {int(k): datetime.timedelta(seconds=v) for k, v in data['cumulative_service_durations'].items()}
            service_roles = data['service_roles']

async def send_alert(guild, member, action, role=None, total_hours=None, salary=None):
    channel = guild.get_channel(ALERT_CHANNEL_ID)
    if not channel:
        return

    if action == "start":
        embed = discord.Embed(title="Début de Service", color=discord.Color.green())
        embed.add_field(name="Membre", value=member.mention, inline=True)
        embed.add_field(name="Rôle", value=role.upper(), inline=True)
        embed.add_field(name="Heure de début", value=datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S'), inline=True)
        embed.set_thumbnail(url=member.avatar.url)
    elif action == "end":
        embed = discord.Embed(title="Fin de Service", color=discord.Color.red())
        embed.add_field(name="Membre", value=member.mention, inline=True)
        embed.add_field(name="Rôle", value=role.upper(), inline=True)
        embed.add_field(name="Heure de fin", value=datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S'), inline=True)
        embed.add_field(name="Total en service", value=str(total_hours), inline=True)
        embed.add_field(name="Salaire", value=f"${salary:,.2f}", inline=True)
        embed.set_thumbnail(url=member.avatar.url)

    await channel.send(embed=embed)

class ServiceView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Prise de service', style=discord.ButtonStyle.green)
    async def start_service(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        guild = interaction.guild
        en_service_role = discord.utils.get(guild.roles, name=EN_SERVICE_ROLE_NAME)

        # Vérifier l'heure et le jour de la semaine
        now = datetime.datetime.now()
        current_time = now.time()
        day_of_week = now.weekday()  # 0 = lundi, 1 = mardi, ..., 6 = dimanche

        # Vérifier les plages horaires autorisées
        if day_of_week < 5:  # Semaine (lundi à vendredi)
            if not (week_start_time <= current_time or current_time <= week_end_time):
                await interaction.response.send_message("Vous pouvez prendre votre service uniquement entre 18h et 1h du matin (lundi à vendredi).", ephemeral=True)
                return
        else:  # Week-end (samedi et dimanche)
            if not (weekend_start_time <= current_time or current_time <= weekend_end_time):
                await interaction.response.send_message("Vous pouvez prendre votre service uniquement entre 18h et 2h du matin (samedi et dimanche).", ephemeral=True)
                return

        if member.id not in service_start_times:
            # Trouver le rôle de pointage correspondant parmi les rôles Discord de l'utilisateur
            pointage_role = None
            for role in member.roles:
                if role.name in DISCORD_TO_POINTAGE_ROLE:
                    pointage_role = DISCORD_TO_POINTAGE_ROLE[role.name]
                    break

            if pointage_role:
                service_start_times[member.id] = {'time': now}
                service_roles[member.id] = pointage_role
                await member.add_roles(en_service_role)  # Ajouter le rôle "En Service"
                await ServiceView.update_service_message(interaction.channel)
                await interaction.response.send_message(f"{member.mention} a commencé son service en tant que {pointage_role}.", ephemeral=True)
                log_service(member, "start", pointage_role)
                await send_alert(interaction.guild, member, "start", pointage_role)
                await update_voice_channels(guild)  # Mise à jour des canaux vocaux
            else:
                await interaction.response.send_message("Vous n'avez pas de rôle de pointage valide.", ephemeral=True)
        else:
            await interaction.response.send_message(f"{member.mention}, vous êtes déjà en service.", ephemeral=True)
        save_data()

    @discord.ui.button(label='Fin de service', style=discord.ButtonStyle.red)
    async def end_service(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        guild = interaction.guild
        en_service_role = discord.utils.get(guild.roles, name=EN_SERVICE_ROLE_NAME)
        await member.remove_roles(en_service_role)  # Retirer le rôle "En Service"
        await ServiceView.end_service_for_member(member, interaction.channel, interaction)
        await update_voice_channels(guild)  # Mise à jour des canaux vocaux
        save_data()

    @discord.ui.button(label='Voir les stats', style=discord.ButtonStyle.blurple)
    async def view_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        stats_channel = interaction.guild.get_channel(STATS_CHANNEL_ID)
        await ServiceView.send_stats(member, stats_channel)
        await interaction.response.send_message("Vos statistiques ont été envoyées au channel dédié.", ephemeral=True)

    @staticmethod
    async def send_stats(member, channel):
        if member.id in cumulative_service_durations:
            service_duration = cumulative_service_durations[member.id]
            role = service_roles.get(member.id, 'inconnu')
            hourly_rate = HOURLY_RATE.get(role, 0)
            salary = (service_duration.total_seconds() / 3600) * hourly_rate
            embed = ServiceView.create_stats_embed(member, service_duration, salary)
            await channel.send(embed=embed)
        else:
            await channel.send(f"{member.mention} n'a pas encore enregistré de temps de service.")

    @staticmethod
    async def end_service_for_member(member, channel, interaction=None):
        if member.id in service_start_times:
            start_data = service_start_times.pop(member.id)
            start_time = start_data['time']
            role = service_roles.get(member.id, 'inconnu')
            end_time = datetime.datetime.now()
            service_duration = end_time - start_time
            hourly_rate = HOURLY_RATE.get(role, 0)

            if member.id in cumulative_service_durations:
                cumulative_service_durations[member.id] += service_duration
            else:
                cumulative_service_durations[member.id] = service_duration

            total_hours = cumulative_service_durations[member.id].total_seconds() / 3600
            salary = total_hours * hourly_rate

            if interaction:
                await interaction.response.send_message(f"{member.mention}, vous avez terminé votre service.", ephemeral=True)
                await interaction.followup.send(embed=ServiceView.create_stats_embed(member, cumulative_service_durations[member.id], salary), ephemeral=True)
            else:
                await channel.send(embed=ServiceView.create_stats_embed(member, cumulative_service_durations[member.id], salary))

            log_service(member, "end", total_hours=total_hours, salary=salary)
            await send_alert(channel.guild, member, "end", role, total_hours, salary)

            # Mettre à jour le message principal sans en envoyer un nouveau
            if status_message_id:
                main_channel = bot.get_channel(channel.id)
                await ServiceView.update_service_message(main_channel)

    @staticmethod
    async def update_service_message(channel):
        global status_message_id

        embed = discord.Embed(title="Statut du Service", color=discord.Color.dark_gray())
        embed.add_field(name="Instructions", value=(
            "Vous devez démarrer votre pointeuse au début de votre service et l'arrêter lorsque votre service se termine. "
            "Des rapports seront envoyés à la direction en cas de non-respect !\n\n"
            "__Heures de service autorisées entre :__\n"
            "18h et 01h en Semaine !\n"
            "18h et 02h le Week-End !\n\n"
            "Cordialement, Comptabilité"
        ), inline=False)

        signed_in_members = [f"{bot.get_user(uid).mention} ({service_roles.get(uid, 'inconnu')})" for uid in service_start_times]
        if signed_in_members:
            embed.add_field(name=f"Membres en service ({len(signed_in_members)})", value="\n".join(signed_in_members), inline=False)
        else:
            embed.add_field(name="Membres en service (0)", value="Aucun membre en service", inline=False)

        if status_message_id:
            try:
                message = await channel.fetch_message(status_message_id)
                await message.edit(embed=embed, view=ServiceView())
            except discord.NotFound:
                status_message_id = None

        if not status_message_id:
            message = await channel.send(embed=embed, view=ServiceView())
            status_message_id = message.id

    @staticmethod
    def create_stats_embed(member, service_duration, salary):
        total_signed_in = str(format_timedelta(service_duration, granularity='seconds', locale='fr_FR'))
        join_date = format_date(member.joined_at, format='full', locale='fr_FR')
        embed = discord.Embed(title=f"Statistiques de {member.display_name}", color=discord.Color.blue())
        embed.add_field(name="Rejoint le :", value=join_date, inline=True)
        embed.add_field(name="Total en service :", value=total_signed_in, inline=True)
        embed.add_field(name="Gains :", value=f"${salary:,.2f}", inline=True)
        embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text="Feuilles de temps")
        return embed

async def update_voice_channels(guild):
    valid_roles = DISCORD_TO_POINTAGE_ROLE.keys()
    total_members = sum(1 for member in guild.members if any(role.name in valid_roles for role in member.roles))
    en_service_members = sum(1 for member in guild.members if discord.utils.get(member.roles, name=EN_SERVICE_ROLE_NAME))

    total_channel = guild.get_channel(TOTAL_EFFECTIF_CHANNEL_ID)
    en_service_channel = guild.get_channel(EN_SERVICE_CHANNEL_ID)

    if total_channel:
        await total_channel.edit(name=f"🟡 Effectif Total : {total_members}")
    if en_service_channel:
        await en_service_channel.edit(name=f"🟢 En Service : {en_service_members}")

@tasks.loop(minutes=5)  # Mise à jour toutes les 5 minutes
async def update_channels_task():
    for guild in bot.guilds:
        await update_voice_channels(guild)

@tasks.loop(minutes=10)  # Vérifie les services prolongés toutes les 10 minutes
async def check_prolonged_services():
    now = datetime.datetime.now()
    prolonged_duration = datetime.timedelta(hours=2)
    for member_id, start_data in service_start_times.items():
        start_time = start_data['time']
        duration = now - start_time
        if duration > prolonged_duration:
            member = await bot.fetch_user(member_id)
            guild = member.guild
            await send_alert(guild, member, "prolonged")
            # Optionally send a DM to the user
            try:
                await member.send(f"Vous avez dépassé les 2 heures de service. Veuillez terminer votre service si possible.")
            except discord.Forbidden:
                pass

@tasks.loop(minutes=1)  # Vérifie les services à arrêter toutes les minutes
async def check_service_end_times():
    now = datetime.datetime.now()
    current_time = now.time()
    day_of_week = now.weekday()  # 0 = lundi, 1 = mardi, ..., 6 = dimanche

    if (day_of_week < 5 and current_time >= datetime.time(1, 0)) or (day_of_week >= 5 and current_time >= datetime.time(2, 0)):
        for member_id in list(service_start_times.keys()):
            member = await bot.fetch_user(member_id)
            guild = member.guild
            channel = guild.get_channel(1242869207469920256)  # Remplacez par l'ID de votre channel
            await ServiceView.end_service_for_member(member, channel)
            await update_voice_channels(guild)
        save_data()

@bot.event
async def on_ready():
    print(f'Connecté en tant que {bot.user}')
    load_data()  # Charger les données au démarrage du bot
    channel = bot.get_channel(1242869207469920256)  # Remplacez par l'ID de votre channel
    await ServiceView.update_service_message(channel)
    update_channels_task.start()
    check_prolonged_services.start()  # Démarrer la tâche pour vérifier les services prolongés
    check_service_end_times.start()  # Démarrer la tâche pour vérifier les services à arrêter

@bot.event
async def on_error(event, *args, **kwargs):
    print(f"Une erreur est survenue : {event}")

def has_moderator_role():
    async def predicate(ctx):
        roles = [discord.utils.get(ctx.guild.roles, name=role_name) for role_name in MODERATOR_ROLE_NAMES]
        if any(role in ctx.author.roles for role in roles):
            return True
        await ctx.send("Vous n'avez pas les permissions nécessaires pour utiliser cette commande.")
        return False
    return commands.check(predicate)

@bot.command()
@has_moderator_role()
async def cut(ctx, member: discord.Member = None):
    if member is None:
        await ctx.send("Veuillez mentionner un utilisateur pour couper son service. Ex: !cut @utilisateur")
        return

    if member.id in service_start_times:
        await ServiceView.end_service_for_member(member, ctx.channel)
        await ctx.send(f"Le service de {member.mention} a été coupé.")
        # Mettre à jour le message principal de la pointeuse après avoir coupé le service
        main_channel = bot.get_channel(1242869207469920256)  # Remplacez par l'ID de votre channel
        await ServiceView.update_service_message(main_channel)
        save_data()
    else:
        await ctx.send(f"{member.mention} n'est pas actuellement en service.")

@bot.command()
@has_moderator_role()
async def deduct(ctx, member: discord.Member = None, hours: int = 0, minutes: int = 0):
    if member is None or (hours <= 0 and minutes <= 0):
        await ctx.send("Veuillez mentionner un utilisateur et un nombre d'heures et/ou de minutes à soustraire. Ex: !deduct @utilisateur 2 30")
        return

    if member.id in cumulative_service_durations:
        deduction = datetime.timedelta(hours=hours, minutes=minutes)
        cumulative_service_durations[member.id] -= deduction
        await ctx.send(f"{hours} heures et {minutes} minutes ont été soustraites du service de {member.mention}.")
        save_data()
    else:
        await ctx.send(f"{member.mention} n'a pas encore enregistré de temps de service.")

@bot.command()
@has_moderator_role()
async def add(ctx, member: discord.Member = None, hours: int = 0, minutes: int = 0):
    if member is None or (hours <= 0 and minutes <= 0):
        await ctx.send("Veuillez mentionner un utilisateur et un nombre d'heures et/ou de minutes à ajouter. Ex: !add @utilisateur 2 30")
        return

    if member.id in cumulative_service_durations:
        addition = datetime.timedelta(hours=hours, minutes=minutes)
        cumulative_service_durations[member.id] += addition
    else:
        cumulative_service_durations[member.id] = datetime.timedelta(hours=hours, minutes=minutes)
    await ctx.send(f"{hours} heures et {minutes} minutes ont été ajoutées au service de {member.mention}.")
    save_data()

@bot.command()
@has_moderator_role()
async def set_service_hours(ctx, day: str, start: str, end: str):
    global week_start_time, week_end_time, weekend_start_time, weekend_end_time

    try:
        start_time = datetime.datetime.strptime(start, '%H:%M').time()
        end_time = datetime.datetime.strptime(end, '%H:%M').time()
    except ValueError:
        await ctx.send("Format de l'heure invalide. Utilisez HH:MM.")
        return

    if day.lower() == 'week':
        week_start_time = start_time
        week_end_time = end_time
        await ctx.send(f"Heures de service en semaine mises à jour : {start} - {end}")
    elif day.lower() == 'weekend':
        weekend_start_time = start_time
        weekend_end_time = end_time
        await ctx.send(f"Heures de service le week-end mises à jour : {start} - {end}")
    else:
        await ctx.send("Jour invalide. Utilisez 'week' pour la semaine et 'weekend' pour le week-end.")
    save_data()

@bot.command()
async def showlogs(ctx):
    if not os.path.exists(LOG_FILE):
        await ctx.send("Aucun log disponible.")
        return

    with open(LOG_FILE, 'r') as f:
        logs = f.read()

    if len(logs) > 1900:
        view = LogsView(logs)
        embed = discord.Embed(title=f"Logs (Page 1/{view.max_pages})", description=logs[:1900])
        await ctx.send(embed=embed, view=view)
    else:
        await ctx.send(f"```{logs}```")

@bot.command()
async def stats(ctx, *, member: discord.Member = None):
    if member is None:
        await ctx.send("Veuillez mentionner un utilisateur pour voir ses statistiques. Ex: !stats @utilisateur")
        return

    if member.id in cumulative_service_durations:
        service_duration = cumulative_service_durations[member.id]
        role = service_roles.get(member.id, 'inconnu')
        hourly_rate = HOURLY_RATE.get(role, 0)
        salary = (service_duration.total_seconds() / 3600) * hourly_rate
        await ctx.send(embed=ServiceView.create_stats_embed(member, service_duration, salary))
    else:
        await ctx.send(f"{member.mention} n'a pas encore enregistré de temps de service.")

@bot.command()
async def sumall(ctx):
    if not cumulative_service_durations:
        await ctx.send("Aucun temps de service enregistré.")
        return

    leaderboard = sorted(cumulative_service_durations.items(), key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="Leaderboard", color=discord.Color.gold())

    for i, (member_id, duration) in enumerate(leaderboard, start=1):
        member = await bot.fetch_user(member_id)
        total_hours = duration.total_seconds() / 3600
        role = service_roles.get(member_id, 'inconnu')
        hourly_rate = HOURLY_RATE.get(role, 0)
        salary = total_hours * hourly_rate
        embed.add_field(name=f"{i}. {member.display_name}", value=f"Temps en service: {str(format_timedelta(duration, granularity='seconds', locale='fr_FR'))} | Gains: ${salary:,.2f}", inline=False)

    await ctx.send(embed=embed)

class LogsView(View):
    def __init__(self, logs, **kwargs):
        super().__init__(**kwargs)
        self.logs = logs
        self.page = 0
        self.max_pages = len(logs) // 1900 + (1 if len(logs) % 1900 > 0 else 0)

    async def update_embed(self, interaction: discord.Interaction):
        start = self.page * 1900
        end = start + 1900
        embed = discord.Embed(title=f"Logs (Page {self.page + 1}/{self.max_pages})", description=self.logs[start:end])
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='Précédent', style=discord.ButtonStyle.primary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await self.update_embed(interaction)

    @discord.ui.button(label='Suivant', style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.max_pages - 1:
            self.page += 1
        await self.update_embed(interaction)

if __name__ == '__main__':
    bot.run(TOKEN)
