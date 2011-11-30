from trac.core import *
from trac.web.chrome import INavigationContributor, ITemplateProvider, add_script, add_script_data, add_stylesheet, add_notice
from trac.web.main import IRequestHandler, IRequestFilter
from trac.util import Markup
from trac.util.text import to_unicode
from trac.versioncontrol.api import RepositoryManager
from code_comments.comments import Comments, CommentJSONEncoder

try:
    import json
except ImportError:
    import simplejson as json

class CodeComments(Component):
    implements(INavigationContributor, ITemplateProvider, IRequestFilter)

    href = 'code-comments'

    # INavigationContributor methods
    def get_active_navigation_item(self, req):
        return self.href

    def get_navigation_items(self, req):
        yield 'mainnav', 'code-comments', Markup('<a href="%s">Code Comments</a>' % (
                 req.href('code-comments') ) )

    # ITemplateProvider methods
    def get_templates_dirs(self):
        return [self.get_template_dir()]

    def get_template_dir(self):
        from pkg_resources import resource_filename
        return resource_filename(__name__, 'templates')

    def get_htdocs_dirs(self):
        from pkg_resources import resource_filename
        return [('code-comments', resource_filename(__name__, 'htdocs'))]

    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        add_stylesheet(req, 'code-comments/code-comments.css')
        return template, data, content_type

class JSDataForRequests(CodeComments):
    implements(IRequestFilter)

    js_templates = ['top-comments-block', 'top-comment', 'side-comment', 'add-comment-dialog']

    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if data is None:
            return

        js_data = {
            'formatting_help_url': req.href.wiki('WikiFormatting'),
            'delete_url': req.href('code-comments', 'delete'),
            'templates': self.templates_js_data(),
            'active_comment_id': req.args.get('codecomment'),
            'username': req.authname,
            'is_admin': 'TRAC_ADMIN' in req.perm,
        }

        original_return_value = template, data, content_type

        if req.path_info.startswith('/changeset/'):
            js_data.update(self.changeset_js_data(data))
        elif req.path_info.startswith('/browser'):
            js_data.update(self.browser_js_data(data))
        else:
            return original_return_value

        add_script(req, 'code-comments/json2.js')
        add_script(req, 'code-comments/underscore-min.js')
        add_script(req, 'code-comments/backbone-min.js')
        # jQuery UI includes: UI Core, Interactions, Button & Dialog Widgets, Core Effects, custom theme
        add_script(req, 'code-comments/jquery-ui/jquery-ui.js')
        add_stylesheet(req, 'code-comments/jquery-ui/trac-theme.css')
        add_script(req, 'code-comments/code-comments.js')
        add_script_data(req, {'CodeComments': js_data})
        return original_return_value

    def templates_js_data(self):
        data = {}
        for name in self.js_templates:
            # we want to use the name as JS identifier and we can't have dashes there
            data[name.replace('-', '_')] = self.template_js_data(name)
        return data

    def changeset_js_data(self, data):
        return {'page': 'changeset', 'revision': data['new_rev'], 'path': '', 'selectorToInsertBefore': 'div.diff:first'}

    def browser_js_data(self, data):
        return {'page': 'browser', 'revision': data['rev'], 'path': data['path'], 'selectorToInsertBefore': 'table#info'}

    def template_js_data(self, name):
        file_name = name + '.html'
        return to_unicode(open(self.get_template_dir() + '/js/' + file_name).read())



class ListComments(CodeComments):
    implements(IRequestHandler)

    # IRequestHandler methods
    def match_request(self, req):
        return req.path_info == '/' + self.href

    def process_request(self, req):
        data = {}
        data['reponame'], repos, path = RepositoryManager(self.env).get_repository_by_path('/')
        data['comments'] = Comments(req, self.env).all()
        data['can_delete'] = 'TRAC_ADMIN' in req.perm
        return 'comments.html', data, None

class DeleteCommentForm(CodeComments):
    implements(IRequestHandler)

    # IRequestHandler methods
    def match_request(self, req):
        return req.path_info == '/' + self.href + '/delete'

    def process_request(self, req):
        req.perm.require('TRAC_ADMIN')
        if 'GET' == req.method:
            return self.form(req)
        else:
            return self.delete(req)

    def form(self, req):
        data = {}
        referrer = req.get_header('Referer')
        data['comment'] = Comments(req, self.env).by_id(req.args['id'])
        data['return_to'] = referrer
        return 'delete.html', data, None

    def delete(self, req):
        comment = Comments(req, self.env).by_id(req.args['id'])
        comment.delete()
        add_notice(req, 'Comment deleted.')
        req.redirect(req.args['return_to'] or req.href())

class BundleCommentsRedirect(CodeComments):
    implements(IRequestHandler)

    # IRequestHandler methods
    def match_request(self, req):
        return req.path_info == '/' + self.href + '/bundle'

    def process_request(self, req):
        text = ''
        for id in req.args['ids'].split(','):
            comment = Comments(req, self.env).by_id(id)
            text += """
[%(link)s %(path)s]
%(text)s

""".lstrip() % {'link': comment.trac_link(), 'path': comment.path_revision_line(), 'text': comment.text}
        req.redirect(req.href.newticket(description=text))

class CommentsREST(CodeComments):
    implements(IRequestHandler)

    # IRequestHandler methods
    def match_request(self, req):
        return req.path_info.startswith('/' + self.href + '/comments')

    def return_json(self, req, data, code=200):
        req.send(json.dumps(data, cls=CommentJSONEncoder), 'application/json')

    def process_request(self, req):
        #TODO: catch errors
        if '/' + self.href + '/comments' == req.path_info:
            if 'GET' == req.method:
                self.return_json(req, Comments(req, self.env).search(req.args))
            if 'POST' == req.method:
                comments = Comments(req, self.env)
                id = comments.create(json.loads(req.read()))
                self.return_json(req, comments.by_id(id))