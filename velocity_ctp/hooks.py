app_name = "velocity_ctp"
app_title = "Velocity CTP"
app_publisher = "Muhammad Huzaifa"
app_description = "Cut-to-Pack garment manufacturing app for Velocity Textiles"
app_email = "cma.mhuzaifa786@gmail.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "velocity_ctp",
# 		"logo": "/assets/velocity_ctp/logo.png",
# 		"title": "Velocity CTP",
# 		"route": "/velocity_ctp",
# 		"has_permission": "velocity_ctp.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/velocity_ctp/css/velocity_ctp.css"
# app_include_js = "/assets/velocity_ctp/js/velocity_ctp.js"

# include js, css files in header of web template
# web_include_css = "/assets/velocity_ctp/css/velocity_ctp.css"
# web_include_js = "/assets/velocity_ctp/js/velocity_ctp.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "velocity_ctp/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "velocity_ctp/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "velocity_ctp.utils.jinja_methods",
# 	"filters": "velocity_ctp.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "velocity_ctp.install.before_install"
after_install = "velocity_ctp.setup.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "velocity_ctp.uninstall.before_uninstall"
# after_uninstall = "velocity_ctp.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "velocity_ctp.utils.before_app_install"
# after_app_install = "velocity_ctp.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "velocity_ctp.utils.before_app_uninstall"
# after_app_uninstall = "velocity_ctp.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "velocity_ctp.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "velocity_ctp.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["velocity_ctp.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
doc_events = {
	"Sales Order": {
		"on_cancel": "velocity_ctp.velocity_ctp.doctype.garment_order.garment_order.clear_sales_order_link",
		"on_trash": "velocity_ctp.velocity_ctp.doctype.garment_order.garment_order.clear_sales_order_link",
	}
}

# Fixtures (Velocity records only)
fixtures = [
	{"dt": "Role", "filters": [["name", "=", "Velocity Merchandiser"]]},
	{"dt": "Custom Field", "filters": [["name", "in", ["Sales Order-garment_order"]]]},
]

# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"velocity_ctp.tasks.all"
# 	],
# 	"daily": [
# 		"velocity_ctp.tasks.daily"
# 	],
# 	"hourly": [
# 		"velocity_ctp.tasks.hourly"
# 	],
# 	"weekly": [
# 		"velocity_ctp.tasks.weekly"
# 	],
# 	"monthly": [
# 		"velocity_ctp.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "velocity_ctp.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "velocity_ctp.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "velocity_ctp.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "velocity_ctp.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["velocity_ctp.utils.before_request"]
# after_request = ["velocity_ctp.utils.after_request"]

# Job Events
# ----------
# before_job = ["velocity_ctp.utils.before_job"]
# after_job = ["velocity_ctp.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"velocity_ctp.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
