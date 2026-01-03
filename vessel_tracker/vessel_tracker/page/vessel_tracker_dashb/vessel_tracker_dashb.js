frappe.pages["vessel-tracker-dashb"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Vessel-Tracker-Dashboard"),
		single_column: true,
	});
};

frappe.pages["vessel-tracker-dashb"].on_page_show = function (wrapper) {
	load_desk_page(wrapper);
};

function load_desk_page(wrapper) {
	let $parent = $(wrapper).find(".layout-main-section");
	$parent.empty();

	frappe.require("vessel_tracker_dashb.bundle.jsx").then(() => {
		frappe.vessel_tracker_dashb = new frappe.ui.VesselTrackerDashb({
			wrapper: $parent,
			page: wrapper.page,
		});
	});
}