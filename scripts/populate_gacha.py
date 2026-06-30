"""
Bulk gacha populator.

Discovers historical/political figures via Wikipedia categories, fetches their
images, uploads to Cloudflare R2, and writes new entries directly to the
gacha_characters DB table.

Usage:
    python scripts/populate_gacha.py              # add up to 500 new chars
    python scripts/populate_gacha.py --limit 2000
    python scripts/populate_gacha.py --dry-run    # preview only, no writes
    python scripts/populate_gacha.py --resume     # skip already-attempted slugs
    python scripts/populate_gacha.py --refresh-images  # backfill images for DB chars

Env vars:
    DATABASE_URL   — Postgres connection string (required)
    R2_TOKEN, R2_ACCOUNT_ID, R2_BUCKET, R2_PUBLIC_URL
"""
import argparse
import asyncio
import json
import mimetypes
import os
import random
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import aiohttp
import asyncpg
from dotenv import load_dotenv

load_dotenv()

R2_TOKEN      = os.getenv("R2_TOKEN", "")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "669887f310b5863b8c09e05b37f15243")
R2_BUCKET     = os.getenv("R2_BUCKET", "social-credit-gacha")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "https://pub-ad86c963b8fe456fbeea7b50a4362d70.r2.dev").rstrip("/")
DATABASE_URL  = os.getenv("DATABASE_URL", "")

_RESUME_PATH = os.path.join(os.path.dirname(__file__), ".gacha_attempted.json")

_UA = "SocialCreditBot/2.0 (shiroyeshimura@gmail.com; gacha bulk populator)"

# ── Wikidata occupation QIDs to include ───────────────────────────────────────
# Excludes athletes, entertainers, scientists — keeps political/historical figures
_OCC_QIDS = (
    "wd:Q82955 wd:Q484876 wd:Q806798 wd:Q372436 wd:Q83460 wd:Q388388 "
    "wd:Q35798 wd:Q48352 wd:Q30461 wd:Q216353 wd:Q5741069 wd:Q79188 "
    "wd:Q4964182 wd:Q188094 wd:Q131524 wd:Q43845 wd:Q1476215 wd:Q3368583 "
    "wd:Q765778 wd:Q17351648 wd:Q2500638"
    # Q765778=jurist  Q17351648=political activist  Q2500638=revolutionary
)

_SPARQL = None  # unused — replaced by Wikipedia category discovery

_WIKI_CATEGORIES = [
    # ── Celebrities & entertainers (high-priority — sampled first) ────────────
    "American_film_actors",
    "British_film_actors",
    "American_television_actors",
    "British_television_actors",
    "American_pop_singers",
    "British_pop_singers",
    "American_rhythm_and_blues_singers",
    "American_women_singers",
    "American_men_singers",
    "American_rappers",
    "British_rappers",
    "American_hip_hop_musicians",
    "American_country_music_singers",
    "American_rock_singers",
    "American_talk_show_hosts",
    "American_television_personalities",
    "British_television_personalities",
    "American_women_models",
    "American_men_models",
    # ── Athletes (high-priority) ──────────────────────────────────────────────
    "NBA_players",
    "American_basketball_players",
    "American_football_players",
    "American_professional_wrestlers",
    "Tennis_players",
    "Grand_Slam_singles_champions",
    "Boxing_world_champions",
    "Olympic_gold_medalists",
    "Formula_One_drivers",
    "American_track_and_field_athletes",
    "Major_League_Baseball_players",
    "National_Hockey_League_players",
    "MMA_fighters",
    "Golfers",
    # ── Heads of state ───────────────────────────────────────────────────────
    "Presidents_of_the_United_States",
    "Prime_ministers_of_the_United_Kingdom",
    "Prime_ministers_of_France",
    "Prime_ministers_of_India",
    "Prime_ministers_of_Canada",
    "Prime_ministers_of_Australia",
    "Prime_ministers_of_Japan",
    "Prime_ministers_of_Israel",
    "Prime_ministers_of_Italy",
    "Chancellors_of_Germany",
    "Presidents_of_France",
    "Presidents_of_Russia",
    "Presidents_of_China",
    "Presidents_of_South_Korea",
    "Presidents_of_Brazil",
    "Presidents_of_Mexico",
    "Presidents_of_Argentina",
    "Presidents_of_Turkey",
    "Presidents_of_Iran",
    "Presidents_of_Egypt",
    "Presidents_of_Nigeria",
    "Presidents_of_Indonesia",
    "Presidents_of_Pakistan",
    "Presidents_of_Philippines",
    "Presidents_of_Venezuela",
    "Presidents_of_Cuba",
    "Presidents_of_Chile",
    "Presidents_of_Colombia",
    "Presidents_of_Peru",
    "Presidents_of_Ukraine",
    "Presidents_of_Poland",
    "Presidents_of_South_Africa",
    "Presidents_of_Kenya",
    "Presidents_of_Ghana",
    "Presidents_of_Zimbabwe",
    "Presidents_of_Ethiopia",
    "Presidents_of_Algeria",
    "Presidents_of_Libya",
    "Presidents_of_Iraq",
    "Presidents_of_Syria",
    "Presidents_of_Afghanistan",
    "Secretaries-General_of_the_United_Nations",
    # ── Broad national politician pools (high photo coverage) ────────────────
    "German_politicians",
    "French_politicians",
    "British_politicians",
    "Russian_politicians",
    "Chinese_politicians",
    "American_politicians",
    "Japanese_politicians",
    "Italian_politicians",
    "Spanish_politicians",
    "Indian_politicians",
    "Brazilian_politicians",
    "Canadian_politicians",
    "Australian_politicians",
    "Israeli_politicians",
    "Iranian_politicians",
    "Turkish_politicians",
    "South_Korean_politicians",
    "Polish_politicians",
    "Swedish_politicians",
    "Dutch_politicians",
    "Swiss_politicians",
    "Austrian_politicians",
    "Greek_politicians",
    "Hungarian_politicians",
    "Romanian_politicians",
    "Czech_politicians",
    "Norwegian_politicians",
    "Danish_politicians",
    "Finnish_politicians",
    "Argentine_politicians",
    "Mexican_politicians",
    "Chilean_politicians",
    "Colombian_politicians",
    "Venezuelan_politicians",
    "Cuban_politicians",
    "Egyptian_politicians",
    "South_African_politicians",
    "Nigerian_politicians",
    "Pakistani_politicians",
    "Ukrainian_politicians",
    "Portuguese_politicians",
    "Belgian_politicians",
    "Singaporean_politicians",
    "Saudi_Arabian_politicians",
    "Emirati_politicians",
    "Kenyan_politicians",
    "Ethiopian_politicians",
    "Ghanaian_politicians",
    "Senegalese_politicians",
    "Rwandan_politicians",
    "Zimbabwean_politicians",
    "Congolese_politicians",
    "Tanzanian_politicians",
    "Ugandan_politicians",
    "Sudanese_politicians",
    "Moroccan_politicians",
    "Tunisian_politicians",
    "Algerian_politicians",
    "Libyan_politicians",
    "Syrian_politicians",
    "Lebanese_politicians",
    "Jordanian_politicians",
    "Iraqi_politicians",
    "Yemeni_politicians",
    "Bangladeshi_politicians",
    "Sri_Lankan_politicians",
    "Myanmar_politicians",
    "Thai_politicians",
    "Vietnamese_politicians",
    "Malaysian_politicians",
    "Indonesian_politicians",
    "Filipino_politicians",
    "Peruvian_politicians",
    "Bolivian_politicians",
    "Ecuadorian_politicians",
    "Paraguayan_politicians",
    "Uruguayan_politicians",
    "Cuban_politicians",
    "Guatemalan_politicians",
    "Honduran_politicians",
    "Salvadoran_politicians",
    "Nicaraguan_politicians",
    "Costa_Rican_politicians",
    "Panamanian_politicians",
    "Dominican_Republic_politicians",
    "Haitian_politicians",
    "New_Zealand_politicians",
    "Irish_politicians",
    "Scottish_politicians",
    "Welsh_politicians",
    "Catalan_politicians",
    # ── Soviet / communist ────────────────────────────────────────────────────
    "General_secretaries_of_the_Communist_Party_of_the_Soviet_Union",
    "Leaders_of_the_Soviet_Union",
    "Communist_Party_of_China_politicians",
    "North_Korean_leaders",
    "Marxist_theorists",
    "Bolsheviks",
    "Trotskyists",
    "Maoists",
    "Sandinistas",
    # ── Monarchs ─────────────────────────────────────────────────────────────
    "British_monarchs",
    "French_monarchs",
    "Russian_tsars",
    "Holy_Roman_Emperors",
    "Emperors_of_China",
    "Emperors_of_Japan",
    "Mughal_emperors",
    "Ottoman_sultans",
    "Byzantine_emperors",
    "Caliphs",
    "Mongol_khans",
    "Emperors_of_Rome",
    "Kings_of_Prussia",
    "Kings_of_Spain",
    "Kings_of_Sweden",
    "Kings_of_England",
    "Kings_of_France",
    "Kings_of_Scotland",
    "Kings_of_Portugal",
    "Kings_of_Poland",
    "Kings_of_Denmark",
    "Kings_of_Norway",
    "Kings_of_Hungary",
    "Kings_of_Serbia",
    "Kings_of_Greece",
    "Kings_of_Romania",
    "Shahs_of_Iran",
    "Kings_of_Saudi_Arabia",
    "Kings_of_Jordan",
    "Kings_of_Morocco",
    "Pharaohs_of_Egypt",
    "Sultans_of_the_Ottoman_Empire",
    "Emperors_of_India",
    "Emperors_of_Ethiopia",
    "Rulers_of_the_Aztec_Empire",
    "Sapa_Inca",
    # ── Military ─────────────────────────────────────────────────────────────
    "Field_marshals",
    "Military_strategists",
    "Warlords",
    "Revolutionaries",
    "Military_dictators",
    "Admirals",
    "Generals",
    "American_military_personnel",
    "British_Army_officers",
    "Soviet_military_personnel",
    "French_military_personnel",
    "German_military_personnel",
    "Japanese_military_personnel",
    "Chinese_military_personnel",
    "Russian_military_personnel",
    "Roman_generals",
    "Macedonian_military_personnel",
    "Napoleonic_Wars_generals",
    "World_War_I_generals",
    "World_War_II_generals",
    "Cold_War_military_leaders",
    "Special_forces_personnel",
    "Military_commanders",
    "Pirates",
    "Privateers",
    # ── Scientists ───────────────────────────────────────────────────────────
    "Theoretical_physicists",
    "Experimental_physicists",
    "Chemists",
    "Biologists",
    "Mathematicians",
    "Astronomers",
    "Inventors",
    "Engineers",
    "Nobel_Prize_in_Physics_laureates",
    "Nobel_Prize_in_Chemistry_laureates",
    "Nobel_Prize_in_Physiology_or_Medicine_laureates",
    "Nobel_Prize_in_Economics_laureates",
    # ── Composers & musicians ─────────────────────────────────────────────────
    "Classical_composers",
    "Baroque_composers",
    "Romantic_composers",
    "Opera_composers",
    "Austrian_composers",
    "German_composers",
    "Italian_composers",
    "Russian_composers",
    "French_composers",
    # ── Artists & writers ─────────────────────────────────────────────────────
    "Italian_Renaissance_painters",
    "Dutch_Golden_Age_painters",
    "French_painters",
    "Spanish_painters",
    "German_painters",
    "Sculptors",
    "Architects",
    "Novelists",
    "Poets",
    "Playwrights",
    "English_writers",
    "French_writers",
    "Russian_writers",
    "German_writers",
    "American_writers",
    # ── Philosophers & thinkers ───────────────────────────────────────────────
    "Political_philosophers",
    "Ancient_Greek_philosophers",
    "Economists",
    "Political_theorists",
    "Sociologists",
    "Anarchists",
    "Libertarians",
    "Ancient_Greek_mathematicians",
    "Ancient_Roman_philosophers",
    "Medieval_philosophers",
    # ── Explorers & adventurers ───────────────────────────────────────────────
    "Explorers",
    "Naval_explorers",
    "Conquistadors",
    "Arctic_explorers",
    "African_explorers",
    # ── Religion & ideology ───────────────────────────────────────────────────
    "Popes",
    "Patriarchs",
    "Caliphs",
    "Imams",
    "Theocrats",
    "Religious_reformers",
    "Christian_missionaries",
    # ── Other notable figures ─────────────────────────────────────────────────
    "Nobel_Peace_Prize_laureates",
    "Activists",
    "Civil_rights_leaders",
    "Feminists",
    "Nationalists",
    "Diplomats",
    "Spies",
    "Assassins",
    "Heads_of_state_of_Germany",
    # ── Scientists (extended) ─────────────────────────────────────────────────
    "Nuclear_physicists",
    "Particle_physicists",
    "Astrophysicists",
    "American_physicists",
    "British_physicists",
    "German_physicists",
    "20th-century_physicists",
    "Computer_scientists",
    "Aerospace_engineers",
    # ── Musicians & composers ─────────────────────────────────────────────────
    "Jazz_musicians",
    "Jazz_composers",
    "American_jazz_musicians",
    "American_jazz_singers",
    "American_jazz_pianists",
    "Rock_musicians",
    "American_rock_musicians",
    "Blues_musicians",
    "American_blues_musicians",
    "Soul_musicians",
    "Folk_musicians",
    "Hip-hop_musicians",
    "Rappers",
    "Violinists",
    "Pianists",
    "Guitarists",
    "Opera_singers",
    "Singer-songwriters",
    "Conductors_(music)",
    "American_conductors_(music)",
    "American_musicians",
    "British_musicians",
    "African-American_musicians",
    # ── Painters & visual artists ─────────────────────────────────────────────
    "Impressionist_painters",
    "Post-Impressionist_artists",
    "Surrealist_artists",
    "Cubist_artists",
    "Baroque_painters",
    "Expressionist_painters",
    "American_painters",
    "British_painters",
    "Chinese_painters",
    "Japanese_painters",
    "Photographers",
    "Graphic_artists",
    # ── Writers & literary figures ────────────────────────────────────────────
    "Japanese_writers",
    "Chinese_writers",
    "Spanish_writers",
    "Latin_American_writers",
    "African_writers",
    "Victorian_novelists",
    "Beat_Generation_writers",
    "Modernist_writers",
    "Crime_fiction_writers",
    "Science_fiction_writers",
    "Journalists",
    "Essayists",
    "Ancient_Greek_writers",
    "Ancient_Roman_writers",
    "Medieval_writers",
    "Renaissance_humanists",
    # ── Film & theatre ────────────────────────────────────────────────────────
    "Film_directors",
    "Stage_actors",
    "Comedians",
    # ── Athletes & sportspeople ───────────────────────────────────────────────
    "World_chess_champions",
    "Association_football_players",
    # ── Business & finance ────────────────────────────────────────────────────
    "Businesspeople",
    "Billionaires",
    "Bankers",
    "American_technology_entrepreneurs",
    "Internet_entrepreneurs",
    "American_chief_executives",
    # ── Explorers & adventurers ───────────────────────────────────────────────
    "Aviators",
    "Astronauts",
    "Oceanographers",
    # ── Ancient world ─────────────────────────────────────────────────────────
    "Ancient_Egyptians",
    "Ancient_Greek_politicians",
    "Ancient_Roman_politicians",
    # ── Social movements & humanitarians ──────────────────────────────────────
    "Abolitionists",
    "Suffragists",
    "Anti-apartheid_activists",
    "Human_rights_activists",
    "Environmentalists",

    # ══════════════════════════════════════════════════════════════════════════
    # NEW CATEGORIES
    # ══════════════════════════════════════════════════════════════════════════

    # ── Internet / digital culture ────────────────────────────────────────────
    "YouTubers",
    "American_YouTubers",
    "British_YouTubers",
    "Gaming_YouTubers",
    "Beauty_YouTubers",
    "Twitch_streamers",
    "American_Twitch_streamers",
    "TikTokers",
    "Podcasters",
    "American_podcasters",
    "Social_media_personalities",
    "Internet_celebrities",
    "Video_bloggers",
    "Esports_players",
    "Professional_gamers",
    "Video_game_streamers",

    # ── K-pop & Korean entertainment ─────────────────────────────────────────
    "K-pop_singers",
    "South_Korean_singers",
    "South_Korean_actors",
    "South_Korean_musicians",
    "BTS_members",
    "BLACKPINK_members",
    "K-pop_girl_groups",
    "K-pop_boy_bands",
    "Korean_rappers",
    "Korean_television_personalities",
    "Korean_film_directors",

    # ── Bollywood & Indian entertainment ──────────────────────────────────────
    "Indian_film_actors",
    "Bollywood_actors",
    "Indian_actresses",
    "Indian_singers",
    "Indian_musicians",
    "Indian_film_directors",
    "Tamil_film_actors",
    "Telugu_film_actors",
    "Indian_television_actors",
    "Indian_comedians",

    # ── Latin American entertainment ──────────────────────────────────────────
    "Mexican_singers",
    "Mexican_actors",
    "Brazilian_singers",
    "Brazilian_actors",
    "Colombian_singers",
    "Argentine_singers",
    "Argentine_actors",
    "Latin_pop_singers",
    "Reggaeton_musicians",
    "Latin_Grammy_Award_winners",
    "Spanish_actors",
    "Spanish_singers",
    "Puerto_Rican_singers",
    "Cuban_musicians",

    # ── Anime, manga & Japanese pop culture ──────────────────────────────────
    "Manga_artists",
    "Anime_directors",
    "Japanese_animators",
    "Japanese_voice_actors",
    "Japanese_game_designers",
    "Visual_novel_writers",
    "Japanese_pop_singers",
    "J-pop_singers",
    "Japanese_idols",
    "Japanese_comedians",
    "Japanese_television_personalities",

    # ── Video game industry ───────────────────────────────────────────────────
    "Video_game_designers",
    "Video_game_developers",
    "Video_game_producers",
    "Video_game_directors",
    "American_video_game_designers",
    "Japanese_video_game_designers",
    "Game_programmers",

    # ── Sports (extended) ─────────────────────────────────────────────────────
    "UFC_champions",
    "Mixed_martial_arts_champions",
    "Professional_boxers",
    "WBC_champions",
    "WBA_champions",
    "IBF_champions",
    "WBO_champions",
    "Kickboxers",
    "Brazilian_jiu-jitsu_practitioners",
    "Judokas",
    "Wrestlers",
    "Sumo_wrestlers",
    "Olympic_wrestlers",
    "Olympic_swimmers",
    "Olympic_gymnasts",
    "Olympic_sprinters",
    "Olympic_cyclists",
    "Olympic_weightlifters",
    "Marathon_runners",
    "Rugby_union_players",
    "Rugby_league_players",
    "Cricket_players",
    "Test_cricket_players",
    "Indian_cricketers",
    "Australian_cricketers",
    "English_cricketers",
    "Pakistani_cricketers",
    "West_Indian_cricketers",
    "Association_football_managers",
    "FIFA_World_Cup_winners",
    "UEFA_Champions_League_winners",
    "Premier_League_players",
    "La_Liga_players",
    "Serie_A_players",
    "Bundesliga_players",
    "Brazilian_footballers",
    "Argentine_footballers",
    "French_footballers",
    "German_footballers",
    "Spanish_footballers",
    "Portuguese_footballers",
    "Italian_footballers",
    "English_footballers",
    "Dutch_footballers",
    "African_footballers",
    "Ballon_d'Or_winners",
    "Cyclists",
    "Tour_de_France_winners",
    "Swimmers",
    "Gymnasts",
    "Figure_skaters",
    "Alpine_skiers",
    "Snowboarders",
    "Decathletes",
    "Sprinters",
    "High_jumpers",
    "Long_jumpers",
    "Shot_putters",
    "Javelin_throwers",
    "Race_car_drivers",
    "NASCAR_drivers",
    "IndyCar_drivers",
    "Motorcycle_racers",
    "Surfers",
    "Skateboarders",
    "Rock_climbers",
    "Triathletes",
    "Table_tennis_players",
    "Badminton_players",
    "Volleyball_players",
    "Water_polo_players",
    "Handball_players",
    "Field_hockey_players",
    "American_soccer_players",
    "Women's_soccer_players",
    "WNBA_players",
    "Darts_players",
    "Snooker_players",
    "Pool_players",
    "Poker_players",
    "Speed_skaters",
    "Bobsledders",
    "Luge_athletes",
    "Biathletes",
    "Cross-country_skiers",
    "Ski_jumpers",

    # ── Music (extended & global) ─────────────────────────────────────────────
    "Electronic_music_producers",
    "DJs",
    "EDM_musicians",
    "House_music_DJs",
    "Techno_musicians",
    "Trance_musicians",
    "Drum_and_bass_musicians",
    "Dubstep_musicians",
    "Dance_music_producers",
    "Pop_musicians",
    "Indie_pop_musicians",
    "Alternative_rock_musicians",
    "Heavy_metal_musicians",
    "Death_metal_musicians",
    "Black_metal_musicians",
    "Punk_rock_musicians",
    "Hardcore_punk_musicians",
    "Grunge_musicians",
    "New_wave_musicians",
    "Disco_musicians",
    "Funk_musicians",
    "Reggae_musicians",
    "Jamaican_musicians",
    "Dancehall_musicians",
    "Afrobeats_musicians",
    "Nigerian_musicians",
    "African_musicians",
    "Gospel_musicians",
    "Christian_music_artists",
    "Latin_music_musicians",
    "Salsa_musicians",
    "Bossa_nova_musicians",
    "Samba_musicians",
    "Flamenco_musicians",
    "Tango_musicians",
    "Cumbia_musicians",
    "French_musicians",
    "German_musicians",
    "Italian_musicians",
    "Spanish_musicians",
    "Australian_musicians",
    "Canadian_musicians",
    "Irish_musicians",
    "Swedish_musicians",
    "Norwegian_musicians",
    "Icelandic_musicians",
    "Danish_musicians",
    "Dutch_musicians",
    "Belgian_musicians",
    "Russian_musicians",
    "Ukrainian_musicians",
    "Polish_musicians",
    "Greek_musicians",
    "Turkish_musicians",
    "Arabic_pop_singers",
    "Egyptian_musicians",
    "Lebanese_musicians",
    "Indian_classical_musicians",
    "Qawwali_musicians",
    "Bhangra_musicians",
    "Chinese_musicians",
    "K-pop_producers",
    "Music_video_directors",
    "Record_producers",
    "Music_executives",
    "Bassists",
    "Drummers",
    "Saxophonists",
    "Trumpeters",
    "Cellists",
    "Flutists",
    "Harpists",
    "Accordionists",
    "Banjo_players",
    "Mandolin_players",
    "Sitar_players",
    "Tabla_players",
    "Didgeridoo_players",
    "Boy_bands",
    "Girl_groups",

    # ── Film & television (extended) ──────────────────────────────────────────
    "Hollywood_actors",
    "American_actresses",
    "American_actors",
    "French_actors",
    "German_actors",
    "Italian_actors",
    "Australian_actors",
    "Canadian_actors",
    "Irish_actors",
    "Hong_Kong_actors",
    "Chinese_actors",
    "Japanese_actors",
    "Thai_actors",
    "Nigerian_actors",
    "Ghanaian_actors",
    "South_African_actors",
    "Action_film_actors",
    "Horror_film_actors",
    "Documentary_film_directors",
    "American_film_directors",
    "British_film_directors",
    "French_film_directors",
    "Italian_film_directors",
    "German_film_directors",
    "Japanese_film_directors",
    "Indian_film_directors",
    "Hong_Kong_film_directors",
    "Chinese_film_directors",
    "Iranian_film_directors",
    "South_Korean_film_directors",
    "Mexican_film_directors",
    "Argentine_film_directors",
    "Film_producers",
    "Film_critics",
    "Screenwriters",
    "American_screenwriters",
    "Reality_television_participants",
    "Reality_television_personalities",
    "American_late-night_television_hosts",
    "American_news_anchors",
    "Television_news_presenters",
    "Broadcast_journalists",
    "Radio_personalities",
    "Stand-up_comedians",
    "American_stand-up_comedians",
    "British_comedians",
    "Australian_comedians",
    "Canadian_comedians",
    "Satirists",
    "Impressionists_(entertainers)",
    "Ventriloquists",
    "Magicians",
    "Illusionists",
    "Circus_performers",
    "Stunt_performers",

    # ── Fashion & beauty ──────────────────────────────────────────────────────
    "Fashion_designers",
    "French_fashion_designers",
    "Italian_fashion_designers",
    "American_fashion_designers",
    "British_fashion_designers",
    "Belgian_fashion_designers",
    "Japanese_fashion_designers",
    "Supermodels",
    "Fashion_models",
    "Plus-size_models",
    "Make-up_artists",
    "Hairstylists",
    "Perfumers",
    "Jewellery_designers",
    "Shoe_designers",

    # ── Food & culinary ───────────────────────────────────────────────────────
    "Celebrity_chefs",
    "French_chefs",
    "Italian_chefs",
    "American_chefs",
    "British_chefs",
    "Japanese_chefs",
    "Restaurateurs",
    "Food_critics",
    "Cookbook_authors",
    "Pastry_chefs",
    "Winemakers",
    "Sommeliers",
    "Bartenders",

    # ── Business & tech (extended) ────────────────────────────────────────────
    "Technology_company_founders",
    "Silicon_Valley_entrepreneurs",
    "Venture_capitalists",
    "Hedge_fund_managers",
    "Investment_bankers",
    "Corporate_executives",
    "Chief_executive_officers",
    "Chief_technology_officers",
    "British_businesspeople",
    "German_businesspeople",
    "French_businesspeople",
    "Chinese_businesspeople",
    "Indian_businesspeople",
    "Japanese_businesspeople",
    "Russian_oligarchs",
    "Media_moguls",
    "Publishing_executives",
    "Real_estate_developers",
    "Fashion_industry_executives",
    "Cryptocurrency_entrepreneurs",
    "Space_industry_entrepreneurs",
    "Electric_vehicle_entrepreneurs",
    "Social_media_company_founders",
    "E-commerce_entrepreneurs",

    # ── Science & technology (extended) ───────────────────────────────────────
    "Geneticists",
    "Neuroscientists",
    "Cognitive_scientists",
    "Evolutionary_biologists",
    "Ecologists",
    "Marine_biologists",
    "Virologists",
    "Epidemiologists",
    "Immunologists",
    "Oncologists",
    "Surgeons",
    "Psychiatrists",
    "Psychologists",
    "Anthropologists",
    "Archaeologists",
    "Palaeontologists",
    "Geologists",
    "Climatologists",
    "Meteorologists",
    "Materials_scientists",
    "Robotics_researchers",
    "Artificial_intelligence_researchers",
    "Cryptographers",
    "Electrical_engineers",
    "Mechanical_engineers",
    "Civil_engineers",
    "Chemical_engineers",
    "Biomedical_engineers",
    "Nanotechnologists",
    "Quantum_physicists",
    "Cosmologists",
    "Astrobiologists",
    "Science_communicators",
    "Popular_science_writers",
    "Indian_scientists",
    "Chinese_scientists",
    "Japanese_scientists",
    "Russian_scientists",
    "French_scientists",
    "Italian_scientists",
    "Israeli_scientists",

    # ── Arts & architecture (extended) ────────────────────────────────────────
    "Abstract_expressionist_artists",
    "Pop_art_artists",
    "Minimalist_artists",
    "Street_artists",
    "Graffiti_artists",
    "Installation_artists",
    "Performance_artists",
    "Video_artists",
    "Conceptual_artists",
    "Digital_artists",
    "Illustrators",
    "Cartoonists",
    "Comic_book_artists",
    "Caricaturists",
    "Portrait_photographers",
    "War_photographers",
    "Fashion_photographers",
    "Wildlife_photographers",
    "Documentary_photographers",
    "Indian_painters",
    "African_painters",
    "Latin_American_painters",
    "Australian_painters",
    "Canadian_painters",
    "Korean_painters",
    "Modernist_architects",
    "Contemporary_architects",
    "American_architects",
    "British_architects",
    "French_architects",
    "Japanese_architects",
    "Landscape_architects",
    "Interior_designers",
    "Graphic_designers",
    "Industrial_designers",
    "Typographers",
    "Textile_designers",
    "Ceramicists",
    "Glass_artists",
    "Printmakers",
    "Engravers",
    "Calligraphers",
    "Muralists",
    "Mosaic_artists",
    "Tattoo_artists",
    "Ballet_dancers",
    "Contemporary_dancers",
    "Choreographers",
    "Ballroom_dancers",
    "Hip-hop_dancers",
    "Flamenco_dancers",

    # ── Writers & media (extended) ────────────────────────────────────────────
    "Indian_writers",
    "Arabic_writers",
    "Persian_writers",
    "Turkish_writers",
    "Korean_writers",
    "African-American_writers",
    "Irish_writers",
    "Australian_writers",
    "Canadian_writers",
    "New_Zealand_writers",
    "Scandinavian_writers",
    "Polish_writers",
    "Hungarian_writers",
    "Czech_writers",
    "Yugoslav_writers",
    "Greek_writers",
    "Romanian_writers",
    "Dutch_writers",
    "Belgian_writers",
    "Swiss_writers",
    "Israeli_writers",
    "Yiddish_writers",
    "Nobel_Prize_in_Literature_laureates",
    "Booker_Prize_winners",
    "Pulitzer_Prize_winners",
    "Fantasy_writers",
    "Horror_writers",
    "Mystery_writers",
    "Thriller_writers",
    "Children's_literature_authors",
    "Young_adult_literature_authors",
    "Graphic_novel_writers",
    "Comic_book_writers",
    "Biographers",
    "Autobiographers",
    "Memoirists",
    "Travel_writers",
    "Nature_writers",
    "Sports_journalists",
    "War_correspondents",
    "Investigative_journalists",
    "Bloggers",
    "Columnists",
    "Editors",
    "Literary_critics",
    "Television_critics",
    "Film_critics",
    "Music_critics",

    # ── Philosophy & academia (extended) ─────────────────────────────────────
    "Continental_philosophers",
    "Analytic_philosophers",
    "Pragmatist_philosophers",
    "Existentialist_philosophers",
    "Phenomenologists",
    "Postmodern_philosophers",
    "Feminist_philosophers",
    "Ethicists",
    "Logicians",
    "Philosophers_of_science",
    "Philosophers_of_language",
    "Philosophers_of_mind",
    "Metaphysicians",
    "Epistemologists",
    "Eastern_philosophers",
    "Buddhist_philosophers",
    "Confucian_philosophers",
    "Taoist_philosophers",
    "Islamic_philosophers",
    "Jewish_philosophers",
    "Christian_philosophers",
    "Utilitarians",
    "Kantian_philosophers",
    "Hegelians",
    "Marxist_philosophers",
    "Linguists",
    "Psycholinguists",
    "Computational_linguists",
    "Semioticians",
    "Rhetoricians",
    "Historians",
    "Military_historians",
    "Economic_historians",
    "Cultural_historians",
    "Intellectual_historians",
    "American_historians",
    "British_historians",
    "French_historians",
    "German_historians",
    "Indian_historians",
    "Ancient_historians",
    "Byzantine_historians",
    "Islamic_historians",
    "Classicists",
    "Orientalists",

    # ── Religion (extended) ───────────────────────────────────────────────────
    "Archbishops",
    "Cardinals",
    "Bishops",
    "Rabbis",
    "Ayatollahs",
    "Muftis",
    "Dalai_Lamas",
    "Buddhist_monks",
    "Sufi_mystics",
    "Hindu_religious_leaders",
    "Sikh_religious_leaders",
    "New_religious_movement_leaders",
    "Cult_leaders",
    "Evangelists",
    "Televangelists",
    "Protestant_reformers",
    "Puritan_ministers",
    "Jesuit_missionaries",
    "Saints",
    "Martyrs",
    "Mystics",
    "Theologians",

    # ── Law & justice ─────────────────────────────────────────────────────────
    "Chief_justices_of_the_United_States",
    "Judges",
    "Lawyers",
    "Prosecutors",
    "Defense_attorneys",
    "International_law_scholars",
    "Legal_reformers",
    "Law_professors",
    "Attorneys_General_of_the_United_States",
    "Solicitors_General",
    "International_Criminal_Court_prosecutors",

    # ── Criminology & true crime ──────────────────────────────────────────────
    "Serial_killers",
    "Criminals",
    "Gangsters",
    "Mobsters",
    "Drug_lords",
    "Hackers",
    "Con_artists",
    "Terrorists",
    "Bombers",
    "Bank_robbers",
    "Kidnappers",
    "Fraudsters",
    "White-collar_criminals",

    # ── Health & medicine ─────────────────────────────────────────────────────
    "Physicians",
    "Medical_pioneers",
    "Vaccinologists",
    "Pharmacologists",
    "Anaesthesiologists",
    "Cardiologists",
    "Neurologists",
    "Paediatricians",
    "Gynaecologists",
    "Ophthalmologists",
    "Dentists",
    "Nurses",
    "Public_health_advocates",
    "Alternative_medicine_practitioners",
    "Nutritionists",
    "Fitness_trainers",

    # ── Education ─────────────────────────────────────────────────────────────
    "University_presidents",
    "Educational_reformers",
    "University_professors",
    "School_principals",

    # ── Environment & nature ──────────────────────────────────────────────────
    "Conservationists",
    "Wildlife_biologists",
    "Environmental_activists",
    "Climate_scientists",
    "Zoologists",
    "Ornithologists",
    "Botanists",
    "Entomologists",
    "Primatologists",
    "Animal_rights_activists",
    "National_park_advocates",

    # ── Space exploration ─────────────────────────────────────────────────────
    "Cosmonauts",
    "American_astronauts",
    "Soviet_cosmonauts",
    "Chinese_astronauts",
    "Space_shuttle_astronauts",
    "International_Space_Station_crew",
    "Lunar_astronauts",
    "Private_spaceflight_participants",
    "Aerospace_entrepreneurs",

    # ── LGBTQ+ figures ────────────────────────────────────────────────────────
    "LGBT_activists",
    "LGBT_politicians",
    "LGBT_entertainers",
    "LGBT_writers",
    "Gay_men",
    "Lesbian_women",
    "Bisexual_people",
    "Transgender_women",
    "Transgender_men",
    "Non-binary_people",

    # ── Disability & accessibility ────────────────────────────────────────────
    "Disabled_activists",
    "Blind_people",
    "Deaf_people",
    "Disability_rights_activists",

    # ── Diaspora & international figures ─────────────────────────────────────
    "African-American_politicians",
    "African-American_athletes",
    "African-American_entertainers",
    "Hispanic_and_Latino_Americans",
    "Asian_Americans",
    "Arab_Americans",
    "Jewish_Americans",
    "Irish_Americans",
    "Italian_Americans",
    "Chinese_Americans",
    "Indian_Americans",
    "Korean_Americans",
    "Vietnamese_Americans",
    "Cuban_Americans",
    "Mexican_Americans",
    "British_Indians",
    "British_Pakistanis",
    "British_West_Indians",
    "Black_British_people",
    "Overseas_Chinese",
    "French_people_of_Algerian_descent",

    # ── Historical eras ───────────────────────────────────────────────────────
    "Ancient_Mesopotamians",
    "Ancient_Persians",
    "Ancient_Israelites",
    "Ancient_Chinese",
    "Ancient_Indians",
    "Ancient_Japanese",
    "Ancient_Mesoamericans",
    "Ancient_South_Americans",
    "Celts",
    "Vikings",
    "Anglo-Saxons",
    "Normans",
    "Crusaders",
    "Knights_Templar",
    "Renaissance_people",
    "Reformation_era_people",
    "Age_of_Enlightenment_people",
    "Age_of_Exploration_people",
    "Industrial_Revolution_people",
    "World_War_I_people",
    "World_War_II_people",
    "Cold_War_people",
    "Decolonisation_era_people",

    # ── Miscellaneous notable ─────────────────────────────────────────────────
    "Philanthropists",
    "Social_entrepreneurs",
    "Community_organizers",
    "Labor_leaders",
    "Trade_union_leaders",
    "Economists_(policy)",
    "Central_bank_governors",
    "Intelligence_officers",
    "Whistleblowers",
    "WikiLeaks_associates",
    "Defectors",
    "Refugees",
    "Prisoners_of_conscience",
    "Death_row_inmates",
    "Exiles",
    "Revolutionaries",
    "Guerrillas",
    "Resistance_fighters",
    "Partisans",
    "Mercenaries",
    "Bounty_hunters",
    "Detectives",
    "Forensic_scientists",
    "Coroners",
    "Medical_examiners",
    "Paramedics",
    "Firefighters",
    "Search_and_rescue_personnel",
    "Test_pilots",
    "Mountaineers",
    "Free_solo_climbers",
    "Base_jumpers",
    "Skydivers",
    "Wingsuit_pilots",
    "Deep_sea_divers",
    "Cave_divers",
    "Solo_circumnavigators",
    "Speed_record_holders",
    "Daredevils",
    "Survivalists",
    "Preppers",
    "Futurists",
    "Transhumanists",
    "Singularitarians",
    "Effective_altruists",
]

# ── Faction keyword rules (matched against Wikipedia description + extract) ────
_FACTION_KW: dict[str, list[str]] = {
    "reds": [
        "communist", "marxist", "bolshevik", "maoist", "leninist", "stalinist",
        "trotskyist", "socialist", "proletariat", "viet cong", "red army",
        "people's republic", "viet minh", "sandinista", "workers' party",
        "communist party", "left-wing revolutionary",
    ],
    "strongmen": [
        "dictator", "fascist", "authoritarian", "junta", "totalitarian",
        "supreme leader", "el caudillo", "il duce", "strongman",
        "ayatollah", "supreme guide", "theocrat", "military government",
    ],
    "conquerors": [
        "field marshal", "general", "admiral", "marshal of", "commander-in-chief",
        "conqueror", "warlord", "great khan", "caesar", "war leader",
        "crusade", "invasion", "military conquest", "legionary",
    ],
    "icons": [
        "actor", "actress", "singer", "pop star", "rapper", "musician",
        "entertainer", "performer", "model", "supermodel", "influencer",
        "television personality", "tv personality", "talk show host",
        "footballer", "basketball player", "tennis player", "boxer",
        "athlete", "racing driver", "formula one", "nba", "nfl",
        "olympian", "olympic", "golfer", "wrestler", "mma fighter",
        "mixed martial arts", "youtuber", "streamer", "social media",
        "celebrity", "film actor", "television actor", "comedian",
        "stand-up", "reality television", "reality tv",
        "content creator", "podcaster", "tiktoker", "vlogger",
        "esports", "professional gamer", "twitch", "youtuber",
        "k-pop", "idol", "boy band", "girl group",
        "chef", "restaurateur", "food critic", "culinary",
        "fashion designer", "fashion model", "runway model",
        "dancer", "choreographer", "ballet", "gymnast",
        "dj", "disc jockey", "electronic music", "producer",
        "film director", "screenwriter", "cinematographer",
        "drag queen", "drag performer", "cabaret",
        "magician", "illusionist", "circus",
        "voice actor", "narrator", "host",
        "cricket player", "cricketer", "rugby player",
        "swimmer", "cyclist", "sprinter", "marathon runner",
        "figure skater", "skier", "snowboarder",
        "surfer", "skateboarder", "extreme sports",
        "mountaineer", "climber", "adventurer", "daredevil",
        "professional poker player",
    ],
    "capitalists": [
        "president", "prime minister", "chancellor", "senator", "congressman",
        "conservative", "tory", "liberal democrat", "centre-right",
        "businessman", "entrepreneur", "industrialist", "banker",
        "chief executive", "founder", "magnate", "tycoon", "billionaire",
        "venture capitalist", "hedge fund", "private equity",
        "tech entrepreneur", "startup founder", "ceo", "cto", "cfo",
        "real estate developer", "media mogul", "publishing executive",
        "investment banker", "stockbroker", "financier",
        "crypto", "cryptocurrency", "blockchain entrepreneur",
    ],
    "philosophers": [
        "philosopher", "economist", "political theorist", "intellectual",
        "theologian", "scholar", "jurist", "political scientist",
        "political philosopher", "social theorist",
        "linguist", "anthropologist", "sociologist", "psychologist",
        "historian", "classicist", "archaeologist", "literary critic",
        "ethicist", "logician", "metaphysician", "epistemologist",
        "futurist", "transhumanist", "effective altruist",
        "science communicator", "science writer", "public intellectual",
        "professor", "academic", "researcher", "author",
        "journalist", "columnist", "essayist", "critic",
        "lawyer", "attorney", "judge", "legal scholar",
        "doctor", "physician", "scientist", "inventor",
        "architect", "urban planner", "designer",
    ],
}

# ── Rarity tiers by monthly Wikipedia pageviews ────────────────────────────────
_RARITY: list[tuple[int, str]] = [
    (2_000_000, "legendary"),
    (500_000,   "epic"),
    (80_000,    "rare"),
    (15_000,    "uncommon"),
    (0,         "common"),
]

# ── Stat ranges per faction ────────────────────────────────────────────────────
_STATS: dict[str, dict[str, tuple[int, int]]] = {
    "reds":        {"authority": (68, 96), "military": (38, 82), "charisma": (58, 92)},
    "capitalists": {"authority": (68, 92), "military": (28, 68), "charisma": (58, 95)},
    "conquerors":  {"authority": (68, 98), "military": (80, 100), "charisma": (48, 86)},
    "strongmen":   {"authority": (78, 96), "military": (48, 86), "charisma": (32, 78)},
    "philosophers":{"authority": (22, 62), "military": (4, 28),  "charisma": (58, 92)},
    "icons":       {"authority": (18, 55), "military": (2, 18),  "charisma": (72, 99)},
    "wildcards":   {"authority": (28, 80), "military": (4, 62),  "charisma": (58, 98)},
}


# ── HTTP helpers (urllib for Wikipedia; aiohttp for R2) ───────────────────────
def _sync_get(url: str, headers: dict | None = None) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=14) as r:
            return r.read()
    except Exception:
        return None


async def _aget(url: str, sem: asyncio.Semaphore, headers: dict | None = None) -> bytes | None:
    async with sem:
        data = await asyncio.to_thread(_sync_get, url, headers)
        return data


# ── Wikidata SPARQL discovery ──────────────────────────────────────────────────
def _wiki_langlinks_counts(titles: list[str]) -> dict[str, int]:
    """Batch-fetch number of language editions for each title (50 at a time).
    Returns {title: langlink_count}. Used as a popularity proxy."""
    counts: dict[str, int] = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        params = {
            "action": "query",
            "titles": "|".join(batch),
            "prop": "langlinks",
            "lllimit": "max",
            "format": "json",
        }
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            for page in data.get("query", {}).get("pages", {}).values():
                t = page.get("title", "")
                counts[t] = len(page.get("langlinks", []))
        except Exception:
            pass
        time.sleep(0.05)
    return counts


_CAT_FETCH_MAX = 150

def _wiki_cat_pages(category: str, limit: int) -> tuple[list[str], dict[str, int]]:
    """Fetch up to _CAT_FETCH_MAX members of a category, rank by language-edition count
    (popularity proxy), and return (top `limit` sorted most-popular first, counts dict)."""
    titles: list[str] = []
    cmcontinue = None
    while len(titles) < _CAT_FETCH_MAX:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmtype": "page",
            "cmlimit": min(500, _CAT_FETCH_MAX - len(titles)),
            "format": "json",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception:
            break
        for m in data.get("query", {}).get("categorymembers", []):
            title = m.get("title", "")
            if title and ":" not in title:
                titles.append(title)
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
    if not titles:
        return [], {}
    counts = _wiki_langlinks_counts(titles)
    titles.sort(key=lambda t: counts.get(t, 0), reverse=True)
    return titles[:limit], counts


def _wiki_cat_subcats(category: str) -> list[str]:
    """Return immediate subcategory names (without 'Category:' prefix)."""
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmtype": "subcat",
        "cmlimit": 50,
        "format": "json",
    }
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return [
            m["title"].replace("Category:", "")
            for m in data.get("query", {}).get("categorymembers", [])
        ]
    except Exception:
        return []


# subcategory name fragments to skip (stubs, lists, maintenance cats, non-person groupings)
_SKIP_SUBCAT_KW = (
    "stub", "list", "template", "redirect", "wikipedia", "film", "television",
    "video game", "discography", "bibliography", "awards", "songs", "albums",
    "lgbtq", "by century", "by year", "by country", "by populated place",
    "categories", "navigational",
)


def _sync_wiki_category(category: str, limit: int) -> tuple[list[str], dict[str, int]]:
    """Return (titles, langlinks_counts) from a category + one level of subcategories."""
    seen: set[str] = set()
    out: list[str] = []
    all_counts: dict[str, int] = {}

    def _add(titles: list[str], counts: dict[str, int]):
        all_counts.update(counts)
        for t in titles:
            slug = t.replace(" ", "_")
            if slug not in seen:
                seen.add(slug)
                out.append(t)

    titles, counts = _wiki_cat_pages(category, limit)
    _add(titles, counts)

    for sub in _wiki_cat_subcats(category):
        if any(kw in sub.lower() for kw in _SKIP_SUBCAT_KW):
            continue
        titles, counts = _wiki_cat_pages(sub, 100)
        _add(titles, counts)

    return out[:limit], all_counts


async def discover_figures(fetch_limit: int, existing_wikis: set[str] | None = None) -> list[dict]:
    print(f"Scraping Wikipedia categories for up to {fetch_limit} candidates...")
    existing_wikis = existing_wikis or set()
    seen: set[str] = set()
    out: list[dict] = []
    # Fetch more per category than we need so existing entries don't exhaust the budget.
    # Goal is per_cat NEW entries per category; fetch up to 3x to find them.
    per_cat_new = min(50, max(20, fetch_limit // len(_WIKI_CATEGORIES) + 5))
    per_cat_fetch = min(500, per_cat_new * 3)
    for category in _WIKI_CATEGORIES:
        if len(out) >= fetch_limit:
            break
        titles, counts = await asyncio.to_thread(_sync_wiki_category, category, per_cat_fetch)
        added = 0
        for title in titles:
            slug = title.replace(" ", "_")
            if slug not in seen and slug not in existing_wikis:
                seen.add(slug)
                out.append({"slug": slug, "name": title, "sitelinks": 30, "langlinks": counts.get(title, 30)})
                added += 1
                if added >= per_cat_new:
                    break
        print(f"  {category}: {added} new ({len(out)} total)")
        await asyncio.sleep(0.05)

    print(f"  {len(out)} distinct candidates")
    return out


# ── Wikipedia summary ──────────────────────────────────────────────────────────
# Reject anything whose description matches these — fictional characters,
# TV episodes, novels, films, etc. sneak into politician/monarch categories.
_NOT_PERSON_RE = re.compile(
    # The Wikipedia REST description field is short (e.g. "American physicist",
    # "Prime Minister of the UK"). Reject descriptions that identify a THING, not a PERSON.
    r"fictional"                                    # any "fictional X" → not real
    r"|\bfictitious\b"
    r"|television (series|show|episode|program)"
    r"|\btv (series|show|episode)\b"
    r"|\banimated (series|film|show)\b"
    r"|\bshort story\b"
    r"|\bvideo game\b"
    r"|\bcomic (book|strip)\b"
    r"|\bgraphic novel\b"
    r"|\bpolitical party\b"
    r"|\btrade union\b"
    r"|\bnewspaper\b|\bperiodical\b"
    r"|\bspacecraft\b|\bsatellite\b|\bspace station\b"
    r"|\bhurricane\b|\bcyclone\b|\btyphoon\b|\basteroid\b|\bcomet\b"
    r"|\brecord label\b"
    r"|\bmonument\b|\bstadium\b"
    # "series of novels" / "novel series" / "1865–1880 series by X" — but not "novelist"
    r"|\bnovels?\s+(by|series\b)"
    r"|\b(series|collection) of novels\b"
    r"|\d{3,4}\s*[–\-]\s*\d{2,4}\s+series\b"  # publication year-range + "series"
    r"|\bseries by\b"                            # "series by [author]"
    # episode/season of a show
    r"|\bepisode of\b|\bseason of\b"
    ,
    re.IGNORECASE,
)

_PERSON_DESC_RE = re.compile(
    r"\b("
    r"politician|statesman|president|prime minister|chancellor|"
    r"emperor|empress|king|queen|prince|princess|tsar|sultan|caliph|pharaoh|"
    r"general|admiral|marshal|commander|warlord|"
    r"revolutionary|activist|dictator|secretary.general|"
    r"philosopher|economist|theorist|scholar|jurist|"
    r"businessman|entrepreneur|religious leader|pope|cardinal|imam|"
    r"explorer|conquistador|spy|diplomat|"
    r"physicist|chemist|biologist|mathematician|astronomer|"
    r"engineer|inventor|scientist|"
    r"composer|musician|pianist|violinist|guitarist|drummer|"
    r"singer|conductor|rapper|producer|songwriter|"
    r"painter|sculptor|artist|photographer|architect|"
    r"writer|novelist|poet|playwright|journalist|author|essayist|"
    r"director|actor|actress|comedian|filmmaker|"
    r"boxer|footballer|athlete|chess player|racing driver|"
    r"banker|financier|magnate|tycoon|investor|"
    r"astronaut|aviator|mountaineer|oceanographer"
    r")\b",
    re.IGNORECASE,
)

# Only accept "born"/"died" or an explicit year-range like 1850–1902 — not bare years,
# which appear in episode air dates and book publication dates too.
_BORN_RE = re.compile(r"\b(born|died)\b|\b\d{3,4}\s*[–\-]\s*\d{2,4}\b", re.IGNORECASE)


def _is_person_summary(d: dict) -> bool:
    desc = (d.get("description") or "").strip()
    if _NOT_PERSON_RE.search(desc):
        return False
    return bool(_PERSON_DESC_RE.search(desc)) or bool(_BORN_RE.search(desc))


async def wiki_summary(slug: str, sem: asyncio.Semaphore) -> dict | None:
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(slug)}"
    raw = await _aget(url, sem)
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return {"description": d.get("description", ""), "extract": d.get("extract", "")}
    except Exception:
        return None


# ── Wikidata P21 gender lookup ────────────────────────────────────────────────
# Maps Wikidata gender QIDs to our three values
_GENDER_QID: dict[str, str] = {
    "Q6581097": "male",    # male
    "Q6581072": "female",  # female
    "Q2449503": "female",  # transgender female
    "Q2449532": "male",    # transgender male
    "Q1097630": "other",   # intersex
    "Q48270":   "other",   # non-binary
    "Q505371":  "other",   # agender
}

# Fallback: pronoun-based detection from Wikipedia extract
_HE_RE  = re.compile(r"\b(he|his|him)\b", re.IGNORECASE)
_SHE_RE = re.compile(r"\b(she|her|hers)\b", re.IGNORECASE)


def _gender_from_pronouns(extract: str) -> str | None:
    he  = len(_HE_RE.findall(extract[:500]))
    she = len(_SHE_RE.findall(extract[:500]))
    if he == 0 and she == 0:
        return None
    if she > he:
        return "female"
    if he > she:
        return "male"
    return None


def _sync_wiki_gender(slug: str) -> str | None:
    """Try Wikidata P21 first, then fall back to pronoun detection."""
    # Step 1: get QID from Wikipedia
    combo = {}
    req = urllib.request.Request(
        "https://en.wikipedia.org/w/api.php"
        f"?action=query&titles={urllib.parse.quote(slug, safe='')}"
        "&prop=pageprops&ppprop=wikibase_item&format=json",
        headers={"User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            combo = json.loads(r.read())
    except Exception:
        return None
    qid = None
    for page in combo.get("query", {}).get("pages", {}).values():
        qid = page.get("pageprops", {}).get("wikibase_item")
    if not qid:
        return None
    # Step 2: fetch P21 from Wikidata
    time.sleep(0.15)
    req2 = urllib.request.Request(
        f"https://www.wikidata.org/w/api.php?action=wbgetclaims"
        f"&entity={qid}&property=P21&format=json",
        headers={"User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(req2, timeout=10) as r:
            wd = json.loads(r.read())
    except Exception:
        return None
    for claim in wd.get("claims", {}).get("P21", []):
        gid = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id", "")
        if gid in _GENDER_QID:
            return _GENDER_QID[gid]
    return None


async def wiki_gender(slug: str, sem: asyncio.Semaphore, extract: str = "") -> str | None:
    async with sem:
        result = await asyncio.to_thread(_sync_wiki_gender, slug)
    if result:
        return result
    return _gender_from_pronouns(extract)


# ── Wikipedia monthly pageviews (avg over last 6 months) ──────────────────────
async def wiki_views(slug: str, sem: asyncio.Semaphore) -> int:
    now   = datetime.utcnow()
    start = (now - timedelta(days=180)).strftime("%Y%m%d")
    end   = now.strftime("%Y%m%d")
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
        f"/en.wikipedia/all-access/all-agents/{urllib.parse.quote(slug)}/monthly/{start}/{end}"
    )
    raw = await _aget(url, sem)
    if not raw:
        return 0
    try:
        items = json.loads(raw).get("items", [])
        return sum(i.get("views", 0) for i in items) // len(items) if items else 0
    except Exception:
        return 0


# ── Wikipedia images (Action API via urllib — aiohttp gets 403) ───────────────
_IMG_EXT = re.compile(r"\.(jpe?g|png|webp)$", re.IGNORECASE)
_IMG_SKIP = re.compile(
    r"(signature|logo|coat.of.arms|flag|map|symbol|seal|emblem|icon|commons-logo)",
    re.IGNORECASE,
)

def _resolve_file_url(fname: str) -> str | None:
    """Resolve a Commons filename to a 800px thumbnail URL."""
    url = (
        "https://commons.wikimedia.org/w/api.php"
        f"?action=query&titles=File:{urllib.parse.quote(fname.replace(' ', '_'), safe='')}"
        "&prop=imageinfo&iiprop=url&iiurlwidth=800&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                pages = json.loads(r.read()).get("query", {}).get("pages", {})
            for page in pages.values():
                for ii in page.get("imageinfo", []):
                    return ii.get("thumburl") or ii.get("url") or None
            return None
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(3 + attempt * 2)
            else:
                return None
    return None


def _sync_wiki_infobox_img(slug: str) -> list[str]:
    """Fast path: only fetch the infobox thumbnail (1 API call, no Wikidata/Commons)."""
    req = urllib.request.Request(
        "https://en.wikipedia.org/w/api.php"
        f"?action=query&titles={urllib.parse.quote(slug, safe='')}"
        "&prop=pageimages&piprop=thumbnail&pithumbsize=800&format=json",
        headers={"User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for page in data.get("query", {}).get("pages", {}).values():
            src = page.get("thumbnail", {}).get("source", "")
            if src and _IMG_EXT.search(src) and not _IMG_SKIP.search(src):
                return [src]
    except Exception:
        pass
    return []


def _sync_wiki_imgs(slug: str, max_images: int = 5) -> list[str]:
    """Return up to max_images portrait URLs for a Wikipedia article.

    Strategy:
    1. Wikipedia pageimages thumbnail — the infobox headshot.
    2. Wikidata P18 (image) — canonical portrait property.
    3. Wikimedia Commons MediaSearch with haswbstatement:P180=QID (depicts this person).
    """
    results: list[str] = []
    seen: set[str] = set()

    def _add(url: str) -> bool:
        if url and url not in seen:
            seen.add(url)
            results.append(url)
            return True
        return False

    def _get(url: str, timeout: int = 12) -> dict:
        for attempt in range(3):
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(3 + attempt * 3)
                else:
                    return {}
        return {}

    # 1. Wikipedia infobox thumbnail + QID in one combined call
    combo = _get(
        "https://en.wikipedia.org/w/api.php"
        f"?action=query&titles={urllib.parse.quote(slug, safe='')}"
        "&prop=pageimages|pageprops&piprop=thumbnail&pithumbsize=800"
        "&ppprop=wikibase_item&format=json"
    )
    qid: str | None = None
    for page in combo.get("query", {}).get("pages", {}).values():
        src = page.get("thumbnail", {}).get("source", "")
        if src and _IMG_EXT.search(src) and not _IMG_SKIP.search(src):
            _add(src)
        qid = page.get("pageprops", {}).get("wikibase_item")

    # 1b. REST summary fallback — catches articles where Action API returns no thumbnail/QID
    if not results or not qid:
        rest = _get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(slug, safe='')}")
        orig = rest.get("originalimage", {}).get("source", "")
        if not orig:
            orig = rest.get("thumbnail", {}).get("source", "")
        if orig and _IMG_EXT.search(orig) and not _IMG_SKIP.search(orig):
            _add(orig)
        if not qid:
            # Try to resolve QID via Wikidata entity search
            search_name = rest.get("title", slug.replace("_", " "))
            sq = urllib.parse.quote(search_name)
            wd_search = _get(
                f"https://www.wikidata.org/w/api.php?action=wbsearchentities"
                f"&search={sq}&language=en&limit=1&format=json"
            )
            hits = wd_search.get("search", [])
            if hits:
                qid = hits[0].get("id")

    if len(results) >= max_images or not qid:
        return results

    time.sleep(0.5)

    # 2. Wikidata P18 — canonical portrait(s)
    wd_data = _get(
        f"https://www.wikidata.org/w/api.php?action=wbgetclaims"
        f"&entity={qid}&property=P18&format=json"
    )
    for claim in wd_data.get("claims", {}).get("P18", []):
        if len(results) >= max_images:
            break
        fname = claim.get("mainsnak", {}).get("datavalue", {}).get("value", "")
        if fname and _IMG_EXT.search(fname) and not _IMG_SKIP.search(fname):
            time.sleep(0.3)
            src = _resolve_file_url(fname)
            if src:
                _add(src)

    if len(results) >= max_images:
        return results

    time.sleep(0.5)

    # 3. Commons MediaSearch — haswbstatement:P180=QID (images depicting this person)
    search_q = urllib.parse.quote(f"haswbstatement:P180={qid}", safe=":")
    ms_data = _get(
        f"https://commons.wikimedia.org/w/api.php"
        f"?action=query&list=search&srnamespace=6"
        f"&srsearch={search_q}&srlimit=20&format=json"
    )
    # Prefer cropped/portrait filenames first, then accept any
    hits = ms_data.get("query", {}).get("search", [])
    _PREFER = re.compile(r"(crop|portrait|official|headshot)", re.IGNORECASE)
    hits.sort(key=lambda h: (0 if _PREFER.search(h.get("title", "")) else 1))
    for hit in hits:
        if len(results) >= max_images:
            break
        fname = hit.get("title", "").replace("File:", "")
        if not (_IMG_EXT.search(fname) and not _IMG_SKIP.search(fname)):
            continue
        time.sleep(0.2)
        src = _resolve_file_url(fname)
        if src:
            _add(src)

    return results[:max_images]


def _sync_wiki_img(slug: str) -> str | None:
    imgs = _sync_wiki_imgs(slug, max_images=1)
    return imgs[0] if imgs else None


async def wiki_images(slug: str, sem: asyncio.Semaphore, max_images: int = 5) -> list[str]:
    async with sem:
        return await asyncio.to_thread(_sync_wiki_imgs, slug, max_images)


async def wiki_image(slug: str, sem: asyncio.Semaphore) -> str | None:
    imgs = await wiki_images(slug, sem, max_images=1)
    return imgs[0] if imgs else None


# ── R2 upload ──────────────────────────────────────────────────────────────────
def _sync_dl(url: str) -> tuple[bytes | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read(), r.headers.get_content_type() or "image/jpeg"
    except Exception:
        return None, "image/jpeg"


async def upload_r2(
    session: aiohttp.ClientSession,
    char_id: str,
    img_url: str,
    index: int,
    sem: asyncio.Semaphore,
) -> str | None:
    img_data, ct = await asyncio.to_thread(_sync_dl, img_url)
    if not img_data:
        return None
    ext = mimetypes.guess_extension(ct)
    if ext in (".jpe", ".jpeg", None):
        ext = ".jpg"
    key = f"gacha/{char_id}/{index}{ext}"
    api = (
        f"https://api.cloudflare.com/client/v4/accounts/{R2_ACCOUNT_ID}"
        f"/r2/buckets/{R2_BUCKET}/objects/{key}"
    )
    async with sem:
        try:
            async with session.put(
                api, data=img_data,
                headers={"Authorization": f"Bearer {R2_TOKEN}", "Content-Type": ct},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status in (200, 201):
                    return f"{R2_PUBLIC_URL}/{key}"
        except Exception:
            pass
    return None


async def upload_r2_multi(
    session: aiohttp.ClientSession,
    char_id: str,
    img_urls: list[str],
    sem: asyncio.Semaphore,
) -> list[str]:
    tasks = [upload_r2(session, char_id, url, i + 1, sem) for i, url in enumerate(img_urls)]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]


# ── Derivation helpers ─────────────────────────────────────────────────────────
def derive_faction(description: str, extract: str) -> str:
    text = (description + " " + extract[:400]).lower()
    scores = {f: sum(1 for kw in kws if kw in text) for f, kws in _FACTION_KW.items()}
    best = max(scores, key=lambda f: scores[f])
    return best if scores[best] > 0 else "wildcards"


def derive_rarity(monthly_views: int) -> str:
    for threshold, rarity in _RARITY:
        if monthly_views >= threshold:
            return rarity
    return "common"


def derive_stats(faction: str, sitelinks: int) -> dict:
    fame = min(sitelinks // 8, 12)
    return {
        stat: min(100, random.randint(lo, hi) + fame)
        for stat, (lo, hi) in _STATS.get(faction, _STATS["wildcards"]).items()
    }


def derive_title(description: str, name: str) -> str:
    t = (description or name).strip()
    return t[:65].rsplit(" ", 1)[0] + "..." if len(t) > 68 else t


def make_char_id(name: str, taken: set[str]) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"\s+", "_", re.sub(r"[^a-z0-9\s]", "", n.lower()).strip())
    cid, i = base, 2
    while cid in taken:
        cid, i = f"{base}_{i}", i + 1
    return cid


# ── Process one figure ─────────────────────────────────────────────────────────
async def process_one(
    item: dict,
    r2_session: aiohttp.ClientSession,
    wiki_sem: asyncio.Semaphore,
    r2_sem: asyncio.Semaphore,
    dry_run: bool,
    override_image_url: str | None = None,
    fast: bool = False,
) -> tuple[str, dict] | None:
    slug = item["slug"]
    name = item["name"]

    if fast:
        summary_t = wiki_summary(slug, wiki_sem)
        images_t  = asyncio.sleep(0, result=[]) if override_image_url else asyncio.to_thread(_sync_wiki_infobox_img, slug)
        summary, img_urls = await asyncio.gather(summary_t, images_t)
        if not summary or not _is_person_summary(summary):
            return None
        monthly_views = item.get("langlinks", 30) * 5000
        gender = _gender_from_pronouns(summary.get("extract", ""))
    else:
        summary_t = wiki_summary(slug, wiki_sem)
        views_t   = wiki_views(slug, wiki_sem)
        images_t  = asyncio.sleep(0, result=[]) if override_image_url else wiki_images(slug, wiki_sem, max_images=5)
        gender_t  = wiki_gender(slug, wiki_sem)
        summary, monthly_views, img_urls, gender = await asyncio.gather(summary_t, views_t, images_t, gender_t)
        if not summary or not _is_person_summary(summary):
            return None
        if not gender:
            gender = _gender_from_pronouns(summary.get("extract", ""))

    faction = derive_faction(summary["description"], summary["extract"])
    rarity  = derive_rarity(monthly_views)
    stats   = derive_stats(faction, item["sitelinks"])
    title   = derive_title(summary["description"], name)

    if override_image_url:
        img_urls = [override_image_url]

    public_urls: list[str] = []
    if img_urls and not dry_run:
        char_id_tmp = make_char_id(name, set())
        public_urls = await upload_r2_multi(r2_session, char_id_tmp, img_urls, r2_sem)

    if not public_urls and img_urls and not dry_run:
        return None

    return name, {
        "name":       name,
        "title":      title,
        "faction":    faction,
        "rarity":     rarity,
        "quote":      "",
        "stats":      stats,
        "wiki":       slug,
        "gender":     gender,
        "image_urls": public_urls if public_urls else (img_urls[:1] if dry_run else []),
    }


# ── DB helpers ────────────────────────────────────────────────────────────────
async def _db_connect() -> asyncpg.Connection:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)
    return await asyncpg.connect(DATABASE_URL)


async def _db_existing_wikis(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT wiki FROM gacha_characters WHERE wiki != ''")
    return {row["wiki"] for row in rows}


async def _db_existing_ids(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT character_id FROM gacha_characters")
    return {row["character_id"] for row in rows}


async def _db_upsert(conn: asyncpg.Connection, cid: str, c: dict) -> None:
    s = c.get("stats", {})
    await conn.execute(
        """
        INSERT INTO gacha_characters
            (character_id, name, title, faction, rarity, quote, wiki,
             stat_authority, stat_military, stat_charisma, image_urls, gender)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (character_id) DO UPDATE SET
            name           = EXCLUDED.name,
            title          = EXCLUDED.title,
            faction        = EXCLUDED.faction,
            rarity         = EXCLUDED.rarity,
            quote          = EXCLUDED.quote,
            wiki           = EXCLUDED.wiki,
            stat_authority = EXCLUDED.stat_authority,
            stat_military  = EXCLUDED.stat_military,
            stat_charisma  = EXCLUDED.stat_charisma,
            image_urls     = EXCLUDED.image_urls,
            gender         = COALESCE(EXCLUDED.gender, gacha_characters.gender)
        """,
        cid,
        c["name"], c.get("title", ""), c.get("faction", "wildcards"), c.get("rarity", "common"),
        c.get("quote", ""), c.get("wiki", ""),
        s.get("authority", 50), s.get("military", 50), s.get("charisma", 50),
        c.get("image_urls") or [], c.get("gender"),
    )


# ── Backfill gender for existing characters ───────────────────────────────────
async def backfill_gender(dry_run: bool) -> None:
    conn = await _db_connect()
    rows = await conn.fetch(
        "SELECT character_id, name, wiki FROM gacha_characters WHERE gender IS NULL ORDER BY character_id"
    )
    print(f"{len(rows)} characters have no gender — backfilling...")

    wiki_sem = asyncio.Semaphore(4)

    async def _lookup(row) -> tuple[str, str, str | None]:
        slug = row["wiki"] or row["character_id"].replace("_", " ")
        summary = await wiki_summary(slug, wiki_sem)
        extract = summary.get("extract", "") if summary else ""
        gender = await wiki_gender(slug, wiki_sem, extract=extract)
        return row["character_id"], row["name"], gender

    done = unknown = 0
    batch_size = 10
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        results = await asyncio.gather(*[_lookup(r) for r in batch])
        for cid, name, gender in results:
            label = gender or "unknown"
            print(f"  {'[DRY] ' if dry_run else ''}{name:<36} → {label}")
            if gender:
                done += 1
                if not dry_run:
                    await conn.execute(
                        "UPDATE gacha_characters SET gender = $1 WHERE character_id = $2",
                        gender, cid,
                    )
            else:
                unknown += 1
        await asyncio.sleep(1.0)

    await conn.close()
    print(f"\nDone. {done} gendered, {unknown} still unknown{' (dry run — no writes)' if dry_run else ''}.")


# ── Main ───────────────────────────────────────────────────────────────────────
async def refresh_images(limit: int, dry_run: bool) -> None:
    """Backfill DB characters that have no images."""
    if not dry_run and not R2_TOKEN:
        print("ERROR: R2_TOKEN not set. Use --dry-run or export R2_TOKEN=...")
        sys.exit(1)

    conn = await _db_connect()
    rows = await conn.fetch(
        """
        SELECT character_id, name, wiki FROM gacha_characters
        WHERE enabled = TRUE AND array_length(image_urls, 1) IS NULL AND wiki != ''
        ORDER BY character_id
        """
    )
    targets = [(row["character_id"], row["name"], row["wiki"]) for row in rows]
    await conn.close()

    print(f"{len(targets)} characters with no images — refreshing up to {limit or 'all'}")
    if limit:
        targets = targets[:limit]

    wiki_sem = asyncio.Semaphore(2)
    r2_sem   = asyncio.Semaphore(4)

    conn = await _db_connect()
    async with aiohttp.ClientSession() as r2_session:
        for i in range(0, len(targets), 20):
            batch = targets[i:i + 20]
            tasks = [wiki_images(wiki, wiki_sem, max_images=5) for _, _, wiki in batch]
            results = await asyncio.gather(*tasks)

            for (cid, name, _), img_urls in zip(batch, results):
                if not img_urls:
                    continue
                if not dry_run:
                    uploaded = await upload_r2_multi(r2_session, cid, img_urls, r2_sem)
                    if not uploaded:
                        continue
                    await conn.execute(
                        "UPDATE gacha_characters SET image_urls = $2 WHERE character_id = $1",
                        cid, uploaded,
                    )
                    print(f"  {name:<36} → {len(uploaded)} images")
                else:
                    print(f"  [DRY] {name:<36} → {len(img_urls)} images found")

            await asyncio.sleep(1.0)

    await conn.close()
    print("Done.")


async def main(limit: int, dry_run: bool, resume: bool, fast: bool = False) -> None:
    if not dry_run and not R2_TOKEN:
        print("ERROR: R2_TOKEN not set. Use --dry-run or export R2_TOKEN=...")
        sys.exit(1)

    conn = await _db_connect()
    existing_wikis = await _db_existing_wikis(conn)
    existing_ids   = await _db_existing_ids(conn)

    attempted: set[str] = set()
    if resume and os.path.exists(_RESUME_PATH):
        with open(_RESUME_PATH) as f:
            attempted = set(json.load(f))
        print(f"Resuming — skipping {len(attempted)} previously attempted slugs")

    candidates = await discover_figures(limit * 2, existing_wikis=existing_wikis)
    candidates = [c for c in candidates if c["slug"] not in attempted]
    print(f"After dedup: {len(candidates)} to process (target: {limit})")

    wiki_sem = asyncio.Semaphore(40)
    r2_sem   = asyncio.Semaphore(40)

    added    = 0
    taken_ids = set(existing_ids)
    batch_size = 100

    async with aiohttp.ClientSession() as r2_session:
        for batch_start in range(0, len(candidates), batch_size):
            if added >= limit:
                break

            batch = candidates[batch_start : batch_start + batch_size]
            results = await asyncio.gather(
                *[process_one(item, r2_session, wiki_sem, r2_sem, dry_run, fast=fast) for item in batch],
                return_exceptions=True,
            )

            for item, result in zip(batch, results):
                attempted.add(item["slug"])
                if isinstance(result, Exception) or result is None:
                    continue
                name, char = result
                cid = make_char_id(name, taken_ids)
                taken_ids.add(cid)
                added += 1
                img = "+" if char["image_urls"] else "-"
                print(f"  [{added:>4}] [{img}img] {name:<36} {char['faction']:<13} {char['rarity']}")
                if not dry_run:
                    await _db_upsert(conn, cid, char)
                if added >= limit:
                    break

            if not dry_run:
                with open(_RESUME_PATH, "w") as f:
                    json.dump(list(attempted), f)

            await asyncio.sleep(1.5)

    await conn.close()
    print(f"\nDone. {added} new characters {'previewed' if dry_run else 'written to DB'}.")


async def _prune_imageless(dry_run: bool, watch: bool = False) -> None:
    interval = 30
    total_deleted = 0
    while True:
        conn = await _db_connect()
        rows = await conn.fetch(
            "SELECT character_id, name FROM gacha_characters "
            "WHERE array_length(image_urls, 1) IS NULL OR array_length(image_urls, 1) = 0"
        )
        if rows:
            print(f"Found {len(rows)} imageless characters:")
            for r in rows:
                print(f"  {r['name']}")
            if not dry_run:
                ids = [r["character_id"] for r in rows]
                await conn.execute("DELETE FROM gacha_claims WHERE character_id = ANY($1)", ids)
                await conn.execute("DELETE FROM gacha_character_stats WHERE character_id = ANY($1)", ids)
                await conn.execute("DELETE FROM gacha_wishlists WHERE character_id = ANY($1)", ids)
                await conn.execute("DELETE FROM gacha_characters WHERE character_id = ANY($1)", ids)
                total_deleted += len(ids)
                print(f"Deleted {len(ids)} imageless characters. (total: {total_deleted})")
            else:
                print("Dry run — nothing deleted.")
        elif watch:
            print(f"No imageless characters found. Checking again in {interval}s...")
        await conn.close()
        if not watch:
            break
        await asyncio.sleep(interval)


async def clear_images(dry_run: bool) -> None:
    """Delete every object in the R2 gacha/ prefix and wipe image_urls in DB."""
    if not dry_run and not R2_TOKEN:
        print("ERROR: R2_TOKEN not set.")
        sys.exit(1)

    list_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{R2_ACCOUNT_ID}"
        f"/r2/buckets/{R2_BUCKET}/objects?prefix=gacha%2F&per_page=1000"
    )
    headers = {"Authorization": f"Bearer {R2_TOKEN}"}
    deleted = 0

    async with aiohttp.ClientSession(headers=headers) as session:
        cursor = None
        while True:
            url = list_url + (f"&cursor={cursor}" if cursor else "")
            async with session.get(url) as r:
                data = await r.json()
            result  = data.get("result", [])
            objects = result if isinstance(result, list) else result.get("objects", [])
            if not objects:
                break

            keys = [o["key"] for o in objects]
            print(f"  Found {len(keys)} objects — {'would delete' if dry_run else 'deleting'}...")

            if not dry_run:
                for key in keys:
                    del_one = (
                        f"https://api.cloudflare.com/client/v4/accounts/{R2_ACCOUNT_ID}"
                        f"/r2/buckets/{R2_BUCKET}/objects/{urllib.parse.quote(key, safe='/')}"
                    )
                    async with session.delete(del_one) as dr:
                        if dr.status in (200, 204):
                            deleted += 1
            else:
                deleted += len(keys)

            result_info = data.get("result_info", {})
            cursor = result_info.get("cursor") if isinstance(result_info, dict) else None
            if not cursor or len(objects) < 1000:
                break

    print(f"  {'Would delete' if dry_run else 'Deleted'} {deleted} R2 objects.")

    if not dry_run:
        conn = await _db_connect()
        await conn.execute("UPDATE gacha_characters SET image_urls = '{}'")
        await conn.close()
        print("  Cleared image_urls in DB.")

    print("Done. Now run: python scripts/populate_gacha.py --refresh-images")


async def _add_characters(names: list[str], dry_run: bool, image_url: str | None = None) -> None:
    """Force-add specific people by Wikipedia article name."""
    if not dry_run and not R2_TOKEN:
        print("ERROR: R2_TOKEN not set. Use --dry-run or export R2_TOKEN=...")
        sys.exit(1)

    if image_url and len(names) != 1:
        print("ERROR: --image-url can only be used with exactly one --add name")
        sys.exit(1)

    conn = await _db_connect()
    existing_wikis = await _db_existing_wikis(conn)
    existing_ids   = await _db_existing_ids(conn)
    taken_ids      = set(existing_ids)

    wiki_sem = asyncio.Semaphore(4)
    r2_sem   = asyncio.Semaphore(4)

    async with aiohttp.ClientSession() as r2_session:
        for name in names:
            slug = name.replace(" ", "_")
            if slug in existing_wikis:
                print(f"  SKIP (already exists): {name}")
                continue
            item = {"slug": slug, "name": name, "sitelinks": 30}
            result = await process_one(item, r2_session, wiki_sem, r2_sem, dry_run,
                                       override_image_url=image_url)
            if result is None:
                print(f"  SKIP (no data): {name}")
                continue
            char_name, char = result
            cid = make_char_id(char_name, taken_ids)
            taken_ids.add(cid)
            img = "+" if char["image_urls"] else "-"
            print(f"  [{img}img] {char_name:<36} {char['faction']:<13} {char['rarity']}")
            if not dry_run:
                await _db_upsert(conn, cid, char)

    await conn.close()
    print("Done. Run `reload cogs.gacha` in the bot console to apply.")


async def _delete_character(name_or_id: str) -> None:
    conn = await _db_connect()
    row = await conn.fetchrow(
        "SELECT character_id, name FROM gacha_characters "
        "WHERE character_id = $1 OR LOWER(name) = LOWER($1) LIMIT 1",
        name_or_id,
    )
    if not row:
        print(f"Character not found: {name_or_id!r}")
        await conn.close()
        return
    await conn.execute("DELETE FROM gacha_characters WHERE character_id = $1", row["character_id"])
    await conn.close()
    print(f"Deleted: {row['name']} ({row['character_id']})")
    print("Run `reload gacha` in the bot console (or restart) to apply the change.")


async def _toggle_character(name_or_id: str, enabled: bool) -> None:
    conn = await _db_connect()
    row = await conn.fetchrow(
        "SELECT character_id, name, enabled FROM gacha_characters "
        "WHERE character_id = $1 OR LOWER(name) = LOWER($1) LIMIT 1",
        name_or_id,
    )
    if not row:
        print(f"Character not found: {name_or_id!r}")
        await conn.close()
        return
    await conn.execute(
        "UPDATE gacha_characters SET enabled = $2 WHERE character_id = $1",
        row["character_id"], enabled,
    )
    await conn.close()
    action = "enabled" if enabled else "disabled"
    print(f"{action}: {row['name']} ({row['character_id']})")
    print("Run `reload gacha` in the bot console (or restart) to apply the change.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Bulk gacha character populator")
    ap.add_argument("--limit",   type=int, default=22000,
                    help="Max new characters to add (default 22000)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview without writing files or uploading images")
    ap.add_argument("--resume",  action="store_true",
                    help="Skip slugs already attempted in a previous run")
    ap.add_argument("--refresh-images", action="store_true",
                    help="Backfill existing characters with up to 5 images each (skips new character discovery)")
    ap.add_argument("--backfill-gender", action="store_true",
                    help="Detect and write gender for all existing characters that have none")
    ap.add_argument("--prune-imageless", action="store_true",
                    help="Delete all characters from the DB that have no images")
    ap.add_argument("--watch", action="store_true",
                    help="Used with --prune-imageless: loop every 30s instead of running once")
    ap.add_argument("--fast", action="store_true",
                    help="Skip gender detection and multi-image search; only grab infobox thumbnail (~3x faster)")
    ap.add_argument("--clear-images", action="store_true",
                    help="Delete all R2 gacha images and wipe image_urls in personalities.py")
    ap.add_argument("--add", metavar="NAME", nargs="+",
                    help="Force-add specific people by Wikipedia article name")
    ap.add_argument("--image-url", metavar="URL",
                    help="Override image URL for the single --add name (only used when --add has exactly one name)")
    ap.add_argument("--delete",  metavar="NAME_OR_ID",
                    help="Permanently delete a character by name or ID")
    ap.add_argument("--disable", metavar="NAME_OR_ID",
                    help="Soft-disable a character by name or ID (no reload needed after next cog reload)")
    ap.add_argument("--enable",  metavar="NAME_OR_ID",
                    help="Re-enable a previously disabled character by name or ID")
    args = ap.parse_args()
    if args.add:
        asyncio.run(_add_characters(args.add, args.dry_run, image_url=getattr(args, "image_url", None)))
    elif args.delete:
        asyncio.run(_delete_character(args.delete))
    elif args.disable:
        asyncio.run(_toggle_character(args.disable, False))
    elif args.enable:
        asyncio.run(_toggle_character(args.enable, True))
    elif getattr(args, "clear_images"):
        asyncio.run(clear_images(args.dry_run))
    elif args.refresh_images:
        asyncio.run(refresh_images(args.limit, args.dry_run))
    elif getattr(args, "backfill_gender", False):
        asyncio.run(backfill_gender(args.dry_run))
    elif getattr(args, "prune_imageless", False):
        asyncio.run(_prune_imageless(args.dry_run, watch=getattr(args, "watch", False)))
    else:
        asyncio.run(main(args.limit, args.dry_run, args.resume, fast=getattr(args, "fast", False)))
