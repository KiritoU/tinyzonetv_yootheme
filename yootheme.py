import base64
import logging
import os
import re
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from time import sleep

import requests
from phpserialize import serialize
from slugify import slugify

from _db import database
from settings import CONFIG

logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s", level=logging.INFO)


class Yootheme:
    def __init__(self, film: dict, episodes: dict):
        self.film = film
        self.film["quality"] = self.film["extra_info"].get("quality", "HD")
        self.film["version"] = "English"
        self.film["country"] = self.film["extra_info"].get("Country", "")
        self.film["origin_title"] = self.film["title"]
        self.film["origin_slug"] = self.film["slug"]
        self.season_episodes = {}
        self.season_episode = {}
        self.episodes = episodes

    def get_header(self):
        header = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E150",  # noqa: E501
            "Accept-Encoding": "gzip, deflate",
            # "Cookie": CONFIG.COOKIE,
            "Cache-Control": "max-age=0",
            "Accept-Language": "vi-VN",
            # "Referer": "https://mangabuddy.com/",
        }
        return header

    def download_url(self, url):
        return requests.get(url, headers=self.get_header())

    def error_log(self, msg: str, log_file: str = "failed.log"):
        datetime_msg = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        Path("log").mkdir(parents=True, exist_ok=True)
        with open(os.path.join("log", log_file), "a") as f:
            print(f"{datetime_msg} LOG:  {msg}\n{'-' * 80}", file=f)

    def get_timeupdate(self) -> str:
        # TODO: later
        timeupdate = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return timeupdate

    def format_text(self, text: str) -> str:
        return text.strip().strip("\n").replace("\\", "")

    def get_year_from(self, released: str):
        try:
            dt = datetime.strptime(released, "%Y-%m-%d")
            return int(dt.year)
        except:
            return CONFIG.DEFAULT_RELEASE_YEAR

    def get_season_number(self, season_str: str) -> str:
        season_str = season_str.replace("\n", " ").lower()
        regex = re.compile(r"season\s+(\d+)")
        match = regex.search(season_str)
        if match:
            return match.group(1)
        else:
            return "1"

    def insert_postmeta(self, postmeta_data: list, table: str = "postmeta"):
        database.insert_into(table=table, data=postmeta_data, is_bulk=True)

    def save_thumb(
        self,
        imageUrl: str,
        imageName: str = "0.jpg",
    ) -> str:
        Path(CONFIG.COVER_SAVE_FOLDER).mkdir(parents=True, exist_ok=True)
        saveImage = f"{CONFIG.COVER_SAVE_FOLDER}/{imageName}"

        isNotSaved = not Path(saveImage).is_file()
        if isNotSaved:
            image = self.download_url(imageUrl)
            with open(saveImage, "wb") as f:
                f.write(image.content)
            isNotSaved = True

        return [saveImage, isNotSaved]

    def insert_thumb(self, post_name: str, thumbUrl: str) -> int:
        thumbExtension = thumbUrl.split("/")[-1].split(".")[-1]
        if not thumbExtension:
            return 0

        thumbName = f"{post_name}.{thumbExtension}"

        self.save_thumb(thumbUrl, thumbName)
        timeupdate = self.get_timeupdate()
        thumbPostData = (
            0,
            timeupdate,
            timeupdate,
            "",
            thumbName,
            "",
            "inherit",
            "open",
            "closed",
            "",
            thumbName,
            "",
            "",
            timeupdate,
            timeupdate,
            "",
            0,
            "",
            0,
            "attachment",
            "image/png",
            0,
        )

        thumbId = database.insert_into(table="posts", data=thumbPostData)
        database.insert_into(
            table="postmeta",
            data=(thumbId, "_wp_attached_file", f"covers/{thumbName}"),
        )

        return thumbId

    def insert_taxonomy(
        self,
        post_id: int,
        taxonomies: str,
        taxonomy_kind: str,
        term_slug: str = "",
    ):
        taxonomies = taxonomies.split(",")
        for taxonomy in taxonomies:
            try:
                term_slug = term_slug if term_slug else slugify(taxonomy)
                cols = "tt.term_taxonomy_id"
                table = f"{CONFIG.TABLE_PREFIX}term_taxonomy tt, {CONFIG.TABLE_PREFIX}terms t"
                condition = f't.slug = "{term_slug}" AND tt.term_id=t.term_id AND tt.taxonomy="{taxonomy_kind}"'

                query = f"SELECT {cols} FROM {table} WHERE {condition}"
                beTaxonomyId = database.select_with(query)

                if not beTaxonomyId:
                    taxonomyTermId = database.insert_into(
                        table="terms",
                        data=(taxonomy.capitalize(), term_slug, 0),
                    )
                    taxonomyTermTaxonomyId = database.insert_into(
                        table="term_taxonomy",
                        data=(taxonomyTermId, taxonomy_kind, "", 0, 0),
                    )
                else:
                    taxonomyTermTaxonomyId = beTaxonomyId[0][0]

                try:
                    database.insert_into(
                        table="term_relationships",
                        data=(post_id, taxonomyTermTaxonomyId, 0),
                    )
                except:
                    pass
            except Exception as e:
                self.error_log(
                    msg=f"Error inserting taxonomy: {taxonomy}\n{e}",
                    log_file="helper.insert_taxonomy.log",
                )

    def insert_episode(self, serieId: int, thumbId: int):
        backendSerieEpisode = database.select_all_from(
            table="posts", condition=f"post_name='{self.season_episode['slug']}'"
        )
        if backendSerieEpisode:
            return

        logging.info(f"Inserting episode: {self.season_episode['title']}")
        # self.check_duplicate_serie(serieEpisodeName)

        timeupdate = self.get_timeupdate()
        data = (
            0,
            timeupdate,
            timeupdate,
            # self.film.get("description", ""),
            CONFIG.EPISODE_DEFAULT_DESCRIPTION.format(
                self.season_episode["title"], self.season_episode["title"]
            ),
            self.season_episode["title"],
            "",
            "publish",
            "open",
            "closed",
            "",
            self.season_episode["slug"],
            "",
            "",
            timeupdate,
            timeupdate,
            "",
            serieId,
            "",
            0,
            "chap",
            "",
            0,
        )

        postId = database.insert_into(table=f"posts", data=data)

        postmetas = [
            (postId, "show_tien_to", "0"),
            (postId, "show_trangthai", "0"),
            (postId, "chat_luong_video", "HD"),
            (
                postId,
                "video_link",
                self.season_episode["link"],
            ),
            # (postId, "country", episode["country"]),
            # (postId, "released", episode["released"]),
            (
                postId,
                "trailer",
                "https://www.youtube.com/embed/" + self.film.get("trailer_id", "")
                if self.film.get("trailer_id", "")
                else "",
            ),
            # (postId, "genre", episode["genre"]),
            (postId, "post_views_count", "0"),
        ]

        if thumbId:
            postmetas.append((postId, "_thumbnail_id", thumbId))

        self.insert_postmeta(postmetas)
        # for pmeta in postmetas:
        #     database.insert_into(
        #         table="postmeta",
        #         data=pmeta,
        #     )

        self.insert_taxonomy(postId, "TV Show", "category", term_slug="tv-shows")
        self.insert_taxonomy(postId, self.film["country"], "country")
        self.insert_taxonomy(
            postId, self.film["extra_info"].get("Released", ""), "release"
        )
        self.insert_taxonomy(postId, self.film["extra_info"].get("Genre", ""), "genres")
        # self.insert_taxonomy(postId, [episode["status"]], "status")

    def insert_episodes(self, serieId: int, thumbId: int):
        for episode_number, episode_title in self.season_episodes.items():
            episode_title = (
                self.film["title"]
                + f" Episode {episode_number}"
                + f" - {episode_title}"
            )
            episode_slug = slugify(self.film["slug"] + f" Episode {episode_number}")
            episode_link = f"https://www.2embed.to/embed/tmdb/tv?id={self.episodes.get('tmdb_id', '0')}&s={self.film['season_number']}&e={episode_number}"
            self.season_episode = {
                "title": episode_title,
                "slug": episode_slug,
                "link": episode_link,
            }
            self.insert_episode(serieId, thumbId)

    def insert_root_film(self) -> int:
        serie_slug = self.film["slug"]
        backendSerie = database.select_all_from(
            table="posts", condition=f"post_name='{serie_slug}'", cols="ID"
        )
        if backendSerie:
            try:
                postId = backendSerie[0][0]
                thumb = database.select_all_from(
                    table="postmeta",
                    condition=f"post_id={postId} AND meta_key='_thumbnail_id'",
                    cols="meta_value",
                )
                thumbId = 0
                if thumb and thumb[0] and thumb[0][0]:
                    thumbId = thumb[0][0]
                return [postId, thumbId]
            except Exception as e:
                self.error_log(
                    f"Serie: {serie_slug} - Something went wrong!!!\n{e}",
                    log_file="exitst_post_and_postmeta.log",
                )
                return [0, 0]

        logging.info(f"Inserting root film: {self.film['title']}")
        thumbId = self.insert_thumb(serie_slug, self.film.get("cover_src", ""))
        timeupdate = self.get_timeupdate()
        data = (
            0,
            timeupdate,
            timeupdate,
            self.film.get("description", ""),
            self.film.get("title", ""),
            "",
            "publish",
            "open",
            "closed",
            "",
            self.film.get("slug", ""),
            "",
            "",
            timeupdate,
            timeupdate,
            "",
            0,
            "",
            0,
            "post",
            "",
            0,
        )

        postId = database.insert_into(table=f"posts", data=data)

        postmetas = [
            (postId, "show_tien_to", "0"),
            (postId, "show_trangthai", "0"),
            (postId, "chat_luong_video", "HD"),
            # (postId, "country", serie_details["country"]),
            (postId, "released", self.film["extra_info"].get("Released", "")),
            (
                postId,
                "trailer",
                "https://www.youtube.com/embed/" + self.film.get("trailer_id", "")
                if self.film.get("trailer_id", "")
                else "",
            ),
            # (postId, "genre", serie_details["genre"]),
            (postId, "post_views_count", "0"),
        ]
        if thumbId:
            postmetas.append((postId, "_thumbnail_id", thumbId))

        if self.film["post_type"] == CONFIG.TYPE_TV_SHOWS:
            postmetas.extend(
                [
                    (postId, "tw_multi_chap", "1"),
                    (postId, "film_type", "TV SHOW"),
                    (postId, "tw_parent", postId),
                ]
            )
            self.insert_taxonomy(postId, "TV Show", "category", term_slug="tv-shows")
        else:
            postmetas.extend(
                [
                    (postId, "tw_multi_chap", "0"),
                    (postId, "film_type", ""),
                    (
                        postId,
                        "video_link",
                        f"https://www.2embed.to/embed/tmdb/movie?id={self.episodes.get('tmdb_id', '0')}",
                    ),
                    (postId, "_video_link", "field_601d685ea50eb"),
                ]
            )
            self.insert_taxonomy(postId, "Movies", "category")

        self.insert_postmeta(postmetas)
        # for pmeta in postmetas:
        #     database.insert_into(
        #         table="postmeta",
        #         data=pmeta,
        #     )

        # database.insert_into(table="term_relationships", data=(postId, 1, 0))

        self.insert_taxonomy(postId, self.film["country"], "country")
        self.insert_taxonomy(
            postId, self.film["extra_info"].get("Released", ""), "release"
        )
        self.insert_taxonomy(postId, self.film["extra_info"].get("Genre", ""), "genres")
        # self.insert_taxonomy(postId, [serie_details["status"]], "status")
        # self.insert_taxonomy(postId, serie_details["othername"], "othername")

        return [postId, thumbId]

    def insert_film(self):
        if self.film.get("post_type", CONFIG.TYPE_MOVIE) == CONFIG.TYPE_MOVIE:
            serieId, thumbId = self.insert_root_film()
        else:
            for key, value in self.episodes.items():
                if "season" in key.lower():
                    self.film["season_number"] = self.get_season_number(key)
                    self.film["title"] = self.film["origin_title"] + f" - {key.strip()}"
                    self.film["slug"] = slugify(self.film["origin_slug"] + f" - {key}")
                    serieId, thumbId = self.insert_root_film()
                    self.season_episodes = value
                    self.insert_episodes(serieId, thumbId)
