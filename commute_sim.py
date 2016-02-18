#!/usr/bin/env python
from flask import Flask
from flask import render_template
from flask import jsonify
from pykml import parser
from pykml.factory import nsmap
import googlemaps
import numpy
import os
import sys

import zipfile
import urllib2
import StringIO

app = Flask(__name__)
app.config.from_pyfile('commute_sim.cfg')
try:
    app.config.from_envvar('COMMUTE_SIM_SETTINGS')
except RuntimeError:
    app.logger.debug("Env. var 'COMMUTE_SIM_SETTINGS' unset")
ppl = {}

#with open('commute_sim_example.kml', 'r') as f:
#    root = parser.parse(f).getroot()
fileobject = urllib2.urlopen(app.config['KML_URL'],)
outkmz = zipfile.ZipFile(StringIO.StringIO(fileobject.read()))
with outkmz.open('doc.kml') as f:
    root = parser.parse(f).getroot()
namespace = {"ns": nsmap[None]}
pms = root.xpath(app.config['KML_XPATH'], namespaces=namespace)

if len(pms) == 0:
    raise RuntimeError("Error: xpath query returned zero waypoints ({0}".format(
        app.config['KML_XPATH']))

for pm in pms:
    txt_list = pm.Point.coordinates.text.split(",")[0:2]
    ppl[pm.name.text.strip()] = [float(txt) for txt in reversed(txt_list)]
    app.logger.debug(pm.name.text.strip() + ":" +
        str(ppl[pm.name.text.strip()]))

def distance_matrix_wrapper(lat_lng):
    ppl_keys = ppl.keys()
    ppl_values = ppl.values()
    if len(ppl_values) == 0:
        app.logger.error("No destinations retrieved from KML.")
        return
    gmaps = googlemaps.Client(key=os.environ.get('API_KEY'))
    #https://maps.googleapis.com/maps/api/distancematrix/json?origins=Seattle&destinations=Denver&key=
    # distance_matrix(client, origins, destinations, mode=None, language=None,
    #   avoid=None, units=None, departure_time=None, arrival_time=None,
    #   transit_mode=None, transit_routing_preference=None, traffic_model=None)
    gmap_results = gmaps.distance_matrix(
        lat_lng,
        ppl_values,
        units=app.config['UNITS'])
    app.logger.debug(jsonify(gmap_results))
    if gmap_results["status"] != "OK":
        return gmap_results
    results = gmap_results["rows"][0]
    results["status"] = gmap_results["status"]
    duration_list = []
    for element_idx, row in enumerate(results["elements"]):
        if row["status"] != "OK":
            continue
        app.logger.debug(row)
        duration_list.append(row["duration"]["value"])
        row["duration"]["hhmmss"] = get_hhmmss(row["duration"]["value"])
        row["name"] = ppl_keys[element_idx]
        app.logger.debug(row["name"])

    results["elements"] = sorted(results["elements"],
                                 key=lambda k: k["duration"]["value"] \
                                 if k["status"] == "OK" else sys.maxint)
    results["summary"] = {}
    if len(duration_list) > 0:
        results["summary"]["commute_average"] = \
            get_hhmmss(sum(duration_list) / len(duration_list))
        results["summary"]["commute_total"] = get_hhmmss(sum(duration_list))
        results["summary"]["commute_median"] = \
            get_hhmmss(numpy.median(duration_list))
        results["summary"]["commute_std_dev"] = \
            get_hhmmss(numpy.std(duration_list))
    else:
        results["summary"]["commute_average"] = None
        results["summary"]["commute_total"] = None
        results["summary"]["commute_median"] = None
        results["summary"]["commute_std_dev"] = None
    return results

def get_hhmmss(seconds):
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    return "%02d:%02d:%02d" % (hours, mins, secs)

@app.route('/')
def index():
    return render_template('index.html', title=app.config['TITLE'],
        kml_url=app.config['KML_URL'],
        ppl_count=len(ppl.keys()))

@app.route('/api/commute_stats/<lat_lng>', methods=['GET'])
def commute_stats(lat_lng):
    results = {}
    try:
        results = distance_matrix_wrapper(lat_lng)
    except googlemaps.exceptions.ApiError, ex:
        results["status"] = "API_ERROR"
        app.logger.error("{0}: {1}".format(type(ex).__name__, ex))
    except Exception, ex:
        results["status"] = "UNKNOWN_EXCEPTION"
        app.logger.error("{0}: {1}".format(type(ex).__name__, ex))
    return jsonify(results)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=app.debug)

