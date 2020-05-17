from flask import (
    Blueprint, flash, render_template, request
)

# TODO: Should use md2taiga_cli module
import re
from taiga import TaigaAPI
from collections import deque, defaultdict

import taiga.exceptions

bp = Blueprint('index', __name__)


@bp.route('/', methods=('GET', 'POST'))
def index():
    text = ''
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hostname = request.form['hostname']
        project_name = request.form['project_name']
        text = request.form['text']

        error = None
        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'
        elif not hostname:
            error = 'Hostname is required.'
        elif not project_name:
            error = 'Project name is required.'
        elif not text:
            error = 'Markdown text is required.'
        try:
            api = init_taiga_api(hostname, username, password)
            api.projects.get_by_slug(project_name)
        except taiga.exceptions.TaigaRestException as e:
            if str(e) == 'NETWORK ERROR':
                error = 'Network Error. Check your hostname is correct.'
            else:
                error = str(e)

        if error is None:
            # TODO: Should use md2taiga_cli module
            api = init_taiga_api(hostname, username, password)
            project = api.projects.get_by_slug(project_name)
            lines = text.splitlines()
            level = calc_min_level(lines)
            userstories = create_us_list(lines, level, project)
            text_converted = ''
            for us in userstories:
                line = f'- {us["title"]}\n'
                text_converted += line
                for task in us['task_list']:
                    line = f'\t- {task["title"]}\n'
                    text_converted += line
            if 'create' in request.form:
                add_us_to_project(userstories, project)
                return render_template('index.html')
            return render_template('index.html', username=username, password=password, hostname=hostname, project_name=project_name, text=text, text_converted=text_converted, userstories=userstories)

        flash(error)
    if text != '':
        return render_template('index.html', text=text)
    return render_template('index.html')


def init_taiga_api(host, username, password):
    api = TaigaAPI(
        host=host
    )
    api.auth(
        username=username,
        password=password
    )
    return api


def calc_min_level(lines):
    min_count_hash = float('inf')
    for line in lines:
        if not line.startswith('#'):
            continue
        count_hash = re.match(r'#+', line).end()
        min_count_hash = min(min_count_hash, count_hash)
    return min_count_hash


def get_linums(lines, target_level):
    linums = deque()
    for linum, line in enumerate(lines):
        if not line.startswith('#'):
            continue
        level = re.match(r'#+', line).end()
        if level == target_level:
            linums.append(linum)
    return linums


def create_us_list(lines, level, project):
    us_list = []
    status_name = '着手可能'
    status = project.us_statuses.get(name=status_name).id
    tag_name = 'team: dev'
    tags = {tag_name: project.list_tags()[tag_name]}

    linums_us = get_linums(lines, level)
    for idx, linum in enumerate(linums_us):
        us = defaultdict()
        us['title'] = lines[linum].strip('#').strip()
        if us['title'].startswith('#'):
            # the userstory already exists
            us['exists'] = True
            match_obj = re.match(r'#\d+', us['title'])
            us['id'] = match_obj.group().strip('#')
            us['title'] = us['title'][match_obj.end():].strip()
        else:
            us['exists'] = False
            us['status'] = status
            us['tags'] = tags
        match_obj = re.search(r'\[\d+pt\]', us['title'])
        if match_obj:
            point_name = match_obj.group().strip('[pt]')
        else:
            point_name = '?'
        us['point'] = find_point_id(project, point_name)
        # TODO: Should throw an error when the point is None
        linum_next = linums_us[idx + 1] if not idx == len(linums_us) - 1 else -1
        lines_descoped = lines[linum:linum_next]
        us['task_list'] = create_task_list(lines_descoped, level + 1)
        us_list.append(us)
    return us_list


def create_task_list(lines, level):
    task_list = []
    linums_task = get_linums(lines, level)
    for idx, linum in enumerate(linums_task):
        task = defaultdict()
        task['title'] = lines[linum].strip('#').strip()
        linum_next = linums_task[idx+1] if not idx == len(linums_task) - 1 else -1
        task['desc'] = '\n'.join(lines[linum + 1:linum_next])
        task_list.append(task)
    return task_list


def add_us_to_project(us_list, project):
    for us in us_list:
        if us['exists']:
            # TODO: Should handle error
            us_obj = project.get_userstory_by_ref(us['id'])
            us_obj.subject = us['title']
        else:
            us_obj = project.add_user_story(us['title'], status=us['status'], tags=us['tags'])
        # FIXME: Should specify point to change
        key = next(iter(us_obj.points))
        us_obj.points[key] = us['point']
        us_obj.update()

        for task in us['task_list']:
            us_obj.add_task(
                task['title'],
                project.task_statuses.get(name='New').id,
                description=task['desc'],
            )


def find_point_id(project, name):
    for point in project.list_points():
        if point.name == name:
            return point.id
    return None
