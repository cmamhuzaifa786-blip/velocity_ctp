frappe.listview_settings["Accessory Allocation"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colours = {
			Draft: "red",
			Allocated: "blue",
			"Partly Issued": "orange",
			Issued: "green",
			Released: "gray",
			Cancelled: "red",
		};
		return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
	},
};
