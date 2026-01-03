import * as React from "react";
import { App } from "./App";
import { createRoot } from "react-dom/client";


class VesselTrackerDashb {
	constructor({ page, wrapper }) {
		this.$wrapper = $(wrapper);
		this.page = page;

		this.init();
	}

	init() {
		this.setup_app();
	}


	setup_app() {
		// create and mount the react app
		const root = createRoot(this.$wrapper.get(0));
		root.render(<App />);
		this.$vessel_tracker_dashb = root;
	}
}

frappe.provide("frappe.ui");
frappe.ui.VesselTrackerDashb = VesselTrackerDashb;
export default VesselTrackerDashb;