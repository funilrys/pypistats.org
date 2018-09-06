"""General pages."""
from collections import defaultdict
from copy import deepcopy
import os
import re

from flask import abort
from flask import Blueprint
from flask import current_app
from flask import g
from flask import json
from flask import redirect
from flask import render_template
from flask_wtf import FlaskForm
import requests
from wtforms import StringField
from wtforms.validators import DataRequired

from pypistats.models.download import OverallDownloadCount
from pypistats.models.download import PythonMajorDownloadCount
from pypistats.models.download import PythonMinorDownloadCount
from pypistats.models.download import RECENT_CATEGORIES
from pypistats.models.download import RecentDownloadCount
from pypistats.models.download import SystemDownloadCount

blueprint = Blueprint("general", __name__, template_folder="templates")


MODELS = [
    OverallDownloadCount,
    PythonMajorDownloadCount,
    PythonMinorDownloadCount,
    SystemDownloadCount,
]


class MyForm(FlaskForm):
    """Search form."""

    name = StringField("Package: ", validators=[DataRequired()])


@blueprint.route("/", methods=("GET", "POST"))
def index():
    """Render the home page."""
    form = MyForm()
    if form.validate_on_submit():
        package = form.name.data
        return redirect(f"/search/{package.lower()}")
    package_count = \
        RecentDownloadCount.query.filter_by(category="month").count()
    return render_template(
        "index.html",
        form=form,
        user=g.user,
        package_count=package_count
    )


@blueprint.route("/search/<package>", methods=("GET", "POST"))
def search(package):
    """Render the home page."""
    form = MyForm()
    if form.validate_on_submit():
        package = form.name.data
        return redirect(f"/search/{package}")
    results = RecentDownloadCount.query.filter(
        RecentDownloadCount.package.like(f"{package}%"),
        RecentDownloadCount.category == "month").\
        order_by(RecentDownloadCount.package).\
        limit(20).all()
    packages = [r.package for r in results]
    return render_template(
        "search.html", search=True, form=form, packages=packages, user=g.user
    )


@blueprint.route("/about")
def about():
    """Render the about page."""
    return render_template("about.html", user=g.user)


@blueprint.route("/faqs")
def faqs():
    """Render the FAQs page."""
    return render_template("faqs.html", user=g.user)


@blueprint.route("/packages/<package>")
def package(package):
    """Render the package page."""
    # Recent download stats
    recent_downloads = RecentDownloadCount.query.\
        filter_by(package=package).all()
    if len(recent_downloads) == 0:
        abort(404)
    recent = {r: 0 for r in RECENT_CATEGORIES}
    for r in recent_downloads:
        recent[r.category] = r.downloads

    # PyPI metadata
    metadata = None
    if package != "__all__":
        try:
            metadata = requests.get(
                f"https://pypi.python.org/pypi/{package}/json",
                timeout=5).json()
            if metadata["info"].get("requires_dist", None):
                metadata["requires"] = []
                for required in metadata["info"]["requires_dist"]:
                    metadata["requires"].append(
                        re.split(r"[^0-9a-zA-Z_.-]+", required)[0]
                    )
        except Exception:
            pass

    # Get data from db
    model_data = []
    for model in MODELS:

        if model == OverallDownloadCount:
            metrics = ["downloads"]
        else:
            metrics = ["downloads", "percentages"]

        data = get_download_data(package, model, metrics)

        for idx, metric in enumerate(metrics):
            model_data.append({
                "metric": metric,
                "name": model.__tablename__,
                "data": data[idx],
            })

    # Build the plots
    plots = []
    for model in model_data:
        plot = deepcopy(current_app.config["PLOT_BASE"])[model["metric"]]
        data = []
        for category, values in model["data"].items():
            base = deepcopy(current_app.config["DATA_BASE"][model["metric"]]["data"][0])
            base["x"] = values["x"]
            base["y"] = values["y"]
            if model["metric"] == "percentages":
                base["text"] = values["text"]
            base["name"] = category.title()
            data.append(base)
        plot["data"] = data
        plot["layout"]["title"] = \
            f"Downloads of {package} package - {model['name'].title().replace('_', ' ')}"  # noqa
        plots.append(plot)

    return render_template(
        "package.html",
        package=package,
        plots=plots,
        metadata=metadata,
        recent=recent,
        user=g.user
    )


def get_download_data(package, model, metrics):
    """Get the download data for a package - model."""
    records = model.query.filter_by(package=package).\
        order_by(model.category,
                 model.date).all()
    data = []
    for metric in metrics:
        cumsum = defaultdict(float)
        data_entry = {}
        for record in records:
            category = record.category
            if category not in data_entry:
                data_entry[category] = {"x": [], "y": [], "text": []}
            data_entry[category]["x"].append(str(record.date))
            if metric == "percentages":
                value = getattr(record, metric) or 0
                cumsum[str(record.date)] += value
                data_entry[category]["y"].append(cumsum[str(record.date)])
                data_entry[category]["text"].append("{0:.2f}%".format(value) + " = {:,}".format(record.downloads))
            else:
                data_entry[category]["y"].append(getattr(record, metric) or 0)
        data.append(data_entry)
    return data


@blueprint.route("/top")
def top():
    """Render the top packages page."""
    top = []
    for category in ("day", "week", "month"):
        downloads = RecentDownloadCount.query.filter_by(category=category).\
            filter(RecentDownloadCount.package != "__all__").\
            order_by(RecentDownloadCount.downloads.desc()).limit(20).all()
        top.append({
            "category": category,
            "packages": [{
                "package": d.package,
                "downloads": d.downloads,
            } for d in downloads]
        })
    return render_template("top.html", top=top, user=g.user)


@blueprint.route("/status")
def status():
    """Return OK."""
    return "OK"
