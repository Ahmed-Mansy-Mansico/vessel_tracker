import * as React from "react";

const VesselMap = () => {
  const [vessels, setVessels] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [connectionStatus, setConnectionStatus] = React.useState(false);
  const [selectedPort, setSelectedPort] = React.useState("Jeddah");
  const [nearbyVessels, setNearbyVessels] = React.useState([]);
  const [selectedVessel, setSelectedVessel] = React.useState(null);
  const [mapLoaded, setMapLoaded] = React.useState(false);
  const [isFullscreen, setIsFullscreen] = React.useState(false);
  const mapRef = React.useRef(null);
  const mapInstance = React.useRef(null);
  const markersRef = React.useRef([]);
  const vesselMarkersMap = React.useRef(new Map()); // Track markers by MMSI

  // Saudi Arabia ports
  const ports = [
    { name: "Jeddah", coordinates: { lat: 21.4858, lon: 39.1925 }},
    { name: "Dammam", coordinates: { lat: 26.3927, lon: 50.1059 }},
    { name: "Yanbu", coordinates: { lat: 24.0896, lon: 38.0618 }},
    { name: "Jizan", coordinates: { lat: 16.8892, lon: 42.5511 }},
    { name: "Jubail", coordinates: { lat: 27.0174, lon: 49.6590 }},
    { name: "Rabigh", coordinates: { lat: 22.7981, lon: 39.0367 }}
  ];

  React.useEffect(() => {
    connectToAIS();
    loadExistingVessels(); // Load any existing vessel data from database
    
    // Initialize map after a short delay to ensure DOM is ready
    const initMapTimeout = setTimeout(() => {
      initializeMap();
    }, 500);
    
    return () => {
      clearTimeout(initMapTimeout);
      // Clean up realtime listeners
      frappe.realtime.off("ais_stream");
      // Clean up map and markers
      if (mapInstance.current) {
        vesselMarkersMap.current.clear();
        markersRef.current = [];
        mapInstance.current.remove();
      }
    };
  }, []);

  React.useEffect(() => {
    updateNearbyVessels();
  }, [selectedPort, vessels]);

  // Add effect to update map markers when vessels change
  React.useEffect(() => {
    if (mapInstance.current && vessels.length > 0) {
      updateMapMarkers();
    }
  }, [vessels]);

  const loadExistingVessels = async () => {
    try {
      console.log("Loading existing vessel data from database...");
      const response = await frappe.call({
        method: "vessel_tracker.vessel_tracker.api.live_vessels.get_live_vessels"
      });
      
      if (response.message && response.message.vessels) {
        const dbVessels = response.message.vessels.map(v => ({
          mmsi: v.ais_mmsi,
          vessel_name: v.vessel_name,
          latitude: v.ais_last_position_lat,
          longitude: v.ais_last_position_lon,
          speed: v.ais_speed || 0,
          course: v.ais_course || 0,
          status: v.ais_status || "Unknown",
          timestamp: v.ais_last_update,
          vessel_type: v.vessel_type
        }));
        
        console.log(`Loaded ${dbVessels.length} vessels from database`);
        setVessels(prev => [...prev, ...dbVessels]);
      }
    } catch (error) {
      console.error("Error loading existing vessels:", error);
    }
  };

  const connectToAIS = () => {
    console.log("🔌 Connecting to Frappe Realtime...");
    setLoading(true);
    
    try {
      // Listen for AIS stream events
      frappe.realtime.on("ais_stream", (data) => {
        try {
          console.log("Received AIS data:", data);
          if (data.MessageType === "PositionReport") {
            const report = data.Message.PositionReport;
            addOrUpdateVessel(report, "position");
          } else if (data.MessageType === "ShipStaticData") {
            const staticData = data.Message.ShipStaticData;
            addOrUpdateVessel(staticData, "static");
          }
        } catch (error) {
          console.error("AIS data parse error:", error);
        }
      });
      
      console.log("✅ Connected to Frappe Realtime AIS Stream");
      setConnectionStatus(true);
      setLoading(false);
      
    } catch (error) {
      console.error("Realtime connection error:", error);
      setConnectionStatus(false);
      setLoading(false);
    }
  };

  const addOrUpdateVessel = (data, type) => {
    const mmsi = data.UserID?.toString();
    
    // Debug logging
    console.log(`Processing vessel data:`, {
      type, 
      mmsi, 
      latitude: data.Latitude, 
      longitude: data.Longitude,
      hasPosition: !!(data.Latitude && data.Longitude)
    });
    
    if (!mmsi) {
      console.log("⚠️ No MMSI found in vessel data");
      return;
    }

    setVessels(prev => {
      const existingIndex = prev.findIndex(v => v.mmsi === mmsi);
      
      let vesselData = {};
      if (type === "position") {
        // Validate coordinates are within reasonable bounds for Saudi Arabia area
        if (!data.Latitude || !data.Longitude) {
          console.log(`⚠️ Vessel ${mmsi} missing coordinates:`, {lat: data.Latitude, lon: data.Longitude});
          return prev;
        }
        
        if (data.Latitude < 12 || data.Latitude > 35 || data.Longitude < 32 || data.Longitude > 55) {
          console.log(`⚠️ Vessel ${mmsi} coordinates outside expected area:`, {lat: data.Latitude, lon: data.Longitude});
          // Still process it but log the warning
        }
        
        vesselData = {
          mmsi: mmsi,
          latitude: data.Latitude,
          longitude: data.Longitude,
          speed: data.Sog || 0,
          course: data.Cog || 0,
          status: getNavigationStatus(data.NavigationalStatus || 15),
          timestamp: new Date().toISOString(),
          heading: data.TrueHeading || 0
        };
      } else if (type === "static") {
        vesselData = {
          mmsi: mmsi,
          vessel_name: data.VesselName?.trim() || '',
          call_sign: data.CallSign?.trim() || '',
          imo_number: data.ImoNumber,
          destination: data.Destination?.trim() || '',
          vessel_type: getVesselType(data.Type || 0)
        };
      }

      // Database saving is handled by the AIS worker - no need for duplicate API calls

      if (existingIndex >= 0) {
        const updated = [...prev];
        updated[existingIndex] = { ...updated[existingIndex], ...vesselData };
        console.log(`🔄 Updated existing vessel ${mmsi}:`, updated[existingIndex]);
        return updated;
      } else {
        const newVessel = { ...vesselData };
        console.log(`🆕 Added new vessel ${mmsi}:`, newVessel);
        return [...prev, newVessel];
      }
    });
    
    console.log(`📍 Updated vessel ${mmsi} (${type})`);
  };

  const getNavigationStatus = (statusCode) => {
    const statusMap = {
      0: "Under way using engine", 1: "At anchor", 2: "Not under command",
      3: "Restricted manoeuvrability", 4: "Constrained by her draught", 5: "Moored",
      6: "Aground", 7: "Engaged in Fishing", 8: "Under way sailing", 15: "Default"
    };
    return statusMap[statusCode] || "Unknown";
  };

  const getVesselType = (typeCode) => {
    if (30 <= typeCode && typeCode <= 32) return "Fishing";
    if (60 <= typeCode && typeCode <= 69) return "Passenger";
    if (70 <= typeCode && typeCode <= 79) return "Cargo";
    if (80 <= typeCode && typeCode <= 89) return "Tanker";
    return "Other";
  };

  const calculateDistance = (lat1, lon1, lat2, lon2) => {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon/2) * Math.sin(dLon/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
  };

  const updateNearbyVessels = () => {
    const selectedPortData = ports.find(p => p.name === selectedPort);
    if (!selectedPortData || vessels.length === 0) {
      setNearbyVessels([]);
      return;
    }

    const nearby = vessels.filter(vessel => {
      if (!vessel.latitude || !vessel.longitude) return false;
      
      const distance = calculateDistance(
        selectedPortData.coordinates.lat,
        selectedPortData.coordinates.lon,
        vessel.latitude,
        vessel.longitude
      );
      
      if (distance <= 100) { // 100km radius
        vessel.distance_to_port = Math.round(distance * 10) / 10;
        return true;
      }
      return false;
    }).sort((a, b) => (a.distance_to_port || 0) - (b.distance_to_port || 0));

    setNearbyVessels(nearby.slice(0, 20));
  };


  // Map functions
  const initializeMap = async () => {
    if (!mapRef.current) {
      console.log("Map ref not available");
      return;
    }
    
    try {
      console.log("Initializing map...");
      
      // Load Leaflet CSS and JS if not already loaded
      if (typeof L === 'undefined') {
        console.log("Loading Leaflet library...");
        await loadLeaflet();
      }
      
      // Clear any existing map
      if (mapInstance.current) {
        mapInstance.current.remove();
      }
      
      // Saudi Arabia center coordinates
      const saudiCenter = [24.7136, 46.6753];
      
      // Initialize map with options
      mapInstance.current = L.map(mapRef.current, {
        center: saudiCenter,
        zoom: 6,
        attributionControl: true,
        zoomControl: true
      });
      
      console.log("Map instance created");
      
      // Add OpenStreetMap tiles with error handling
      const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 18,
        errorTileUrl: 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjU2IiBoZWlnaHQ9IjI1NiIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjU2IiBoZWlnaHQ9IjI1NiIgZmlsbD0iI2VlZWVlZSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxOCIgZm9udC1mYW1pbHk9Im1vbm9zcGFjZSIgZmlsbD0iIzk5OTk5OSI+Tm8gVGlsZTwvdGV4dD48L3N2Zz4K'
      });
      
      tileLayer.on('loading', () => console.log('Tiles loading...'));
      tileLayer.on('load', () => console.log('Tiles loaded'));
      tileLayer.on('tileerror', (e) => console.error('Tile error:', e));
      
      tileLayer.addTo(mapInstance.current);
      
      console.log("Adding port markers...");
      // Add port markers
      ports.forEach(port => {
        const portMarker = L.marker([port.coordinates.lat, port.coordinates.lon], {
          icon: L.divIcon({
            className: 'port-marker',
            html: '<div style="background: #dc2626; width: 12px; height: 12px; border-radius: 50%; border: 2px solid white;"></div>',
            iconSize: [16, 16],
            iconAnchor: [8, 8]
          })
        }).addTo(mapInstance.current);
        
        portMarker.bindPopup(`<b>${port.name} Port</b>`);
      });
      
      console.log("Map initialization complete");
      setMapLoaded(true);
      
    } catch (error) {
      console.error("Error initializing map:", error);
      setMapLoaded(false);
    }
  };

  const loadLeaflet = () => {
    return new Promise((resolve, reject) => {
      console.log("Loading Leaflet resources...");
      
      // Add Leaflet CSS
      if (!document.querySelector('link[href*="leaflet.css"]')) {
        const cssLink = document.createElement('link');
        cssLink.rel = 'stylesheet';
        cssLink.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        cssLink.integrity = 'sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=';
        cssLink.crossOrigin = '';
        document.head.appendChild(cssLink);
        console.log("Leaflet CSS loaded");
      }
      
      // Add Leaflet JS
      if (!document.querySelector('script[src*="leaflet.js"]')) {
        const script = document.createElement('script');
        script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        script.integrity = 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=';
        script.crossOrigin = '';
        script.onload = () => {
          console.log("Leaflet JS loaded successfully");
          // Wait a bit for Leaflet to fully initialize
          setTimeout(resolve, 100);
        };
        script.onerror = (error) => {
          console.error("Failed to load Leaflet JS:", error);
          reject(error);
        };
        document.head.appendChild(script);
      } else if (typeof L !== 'undefined') {
        console.log("Leaflet already available");
        resolve();
      } else {
        console.log("Waiting for existing Leaflet to load...");
        // Wait for existing script to load
        setTimeout(() => {
          if (typeof L !== 'undefined') {
            resolve();
          } else {
            reject(new Error("Leaflet failed to load"));
          }
        }, 1000);
      }
    });
  };

  const updateMapMarkers = () => {
    if (!mapInstance.current) return;
    
    // Get current vessel MMSIs
    const currentVesselIds = new Set(vessels.filter(v => v.latitude && v.longitude).map(v => v.mmsi));
    
    // Remove markers for vessels that no longer exist
    vesselMarkersMap.current.forEach((marker, mmsi) => {
      if (!currentVesselIds.has(mmsi)) {
        mapInstance.current.removeLayer(marker);
        vesselMarkersMap.current.delete(mmsi);
        // Also remove from markersRef
        const index = markersRef.current.indexOf(marker);
        if (index > -1) markersRef.current.splice(index, 1);
      }
    });
    
    // Add or update vessel markers
    vessels.forEach(vessel => {
      if (vessel.latitude && vessel.longitude) {
        const existingMarker = vesselMarkersMap.current.get(vessel.mmsi);
        
        if (existingMarker) {
          // Update existing marker position and popup
          existingMarker.setLatLng([vessel.latitude, vessel.longitude]);
          existingMarker.setIcon(L.divIcon({
            className: 'vessel-marker',
            html: getVesselIcon(vessel),
            iconSize: [20, 20],
            iconAnchor: [10, 10]
          }));
          // Update popup content without closing it
          existingMarker.getPopup().setContent(getVesselPopupContent(vessel));
        } else {
          // Create new marker
          const vesselMarker = L.marker([vessel.latitude, vessel.longitude], {
            icon: L.divIcon({
              className: 'vessel-marker',
              html: getVesselIcon(vessel),
              iconSize: [20, 20],
              iconAnchor: [10, 10]
            })
          }).addTo(mapInstance.current);
          
          vesselMarker.bindPopup(getVesselPopupContent(vessel), {
            closeButton: true,
            autoClose: false,
            closeOnEscapeKey: true,
            closeOnClick: false
          });
          
          vesselMarker.on('click', () => {
            setSelectedVessel(vessel);
          });
          
          // Store marker references
          vesselMarkersMap.current.set(vessel.mmsi, vesselMarker);
          markersRef.current.push(vesselMarker);
        }
      }
    });
    
    console.log(`🗺️ Map updated: ${vessels.length} vessels, ${vesselMarkersMap.current.size} markers`);
  };

  const getVesselIcon = (vessel) => {
    const statusColors = {
      "Under way using engine": "#3b82f6",
      "At anchor": "#10b981",
      "Moored": "#8b5cf6",
      "Not under command": "#ef4444",
      "Default": "#6b7280"
    };
    
    const color = statusColors[vessel.status] || statusColors["Default"];
    
    return `
      <div style="
        background: ${color}; 
        width: 16px; 
        height: 16px; 
        border-radius: 50%; 
        border: 2px solid white;
        box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        transform: rotate(${vessel.course || 0}deg);
      ">
        <div style="
          width: 0; 
          height: 0; 
          border-left: 3px solid transparent; 
          border-right: 3px solid transparent; 
          border-bottom: 8px solid white;
          position: absolute;
          top: 2px;
          left: 5px;
        "></div>
      </div>
    `;
  };

  const getVesselPopupContent = (vessel) => {
    return `
      <div style="min-width: 220px; position: relative;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
          <b style="color: #1f2937; font-size: 14px;">${vessel.vessel_name || `MMSI: ${vessel.mmsi}`}</b>
        </div>
        <div style="font-size: 12px; line-height: 1.4; color: #374151;">
          <strong>🚢 Speed:</strong> ${vessel.speed || 0} knots<br>
          <strong>🧭 Course:</strong> ${vessel.course || 0}°<br>
          <strong>📍 Status:</strong> ${vessel.status || "Unknown"}<br>
          ${vessel.destination ? `<strong>🎯 Destination:</strong> ${vessel.destination}<br>` : ''}
          ${vessel.vessel_type ? `<strong>🏷️ Type:</strong> ${vessel.vessel_type}<br>` : ''}
          <strong>🕒 Last Update:</strong> ${new Date(vessel.timestamp).toLocaleString()}
        </div>
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #e5e7eb; font-size: 11px; color: #6b7280;">
          Click vessel for detailed view
        </div>
      </div>
    `;
  };

  const focusOnPort = () => {
    const port = ports.find(p => p.name === selectedPort);
    if (port && mapInstance.current) {
      mapInstance.current.setView([port.coordinates.lat, port.coordinates.lon], 8);
    }
  };

  const reconnect = () => {
    // Clean up existing listeners
    frappe.realtime.off("ais_stream");
    
    setVessels([]);
    setNearbyVessels([]);
    connectToAIS();
  };

  const toggleFullscreen = () => {
    setIsFullscreen(!isFullscreen);
    // Trigger map resize after layout change
    setTimeout(() => {
      if (mapInstance.current) {
        mapInstance.current.invalidateSize();
      }
    }, 300);
  };


  const VesselCard = ({ vessel, showDistance = false }) => (
    <div 
      className="p-4 border rounded-lg hover:bg-gray-50 cursor-pointer"
      onClick={() => setSelectedVessel(vessel)}
    >
      <h4 className="font-semibold text-gray-900">
        🚢 {vessel.vessel_name || `MMSI: ${vessel.mmsi}`}
      </h4>
      <p className="text-sm text-gray-600">
        📍 {vessel.latitude?.toFixed(4)}, {vessel.longitude?.toFixed(4)}
      </p>
      <p className="text-sm text-gray-600">
        ⚡ {vessel.speed || 0} knots | 🧭 {vessel.course || 0}°
      </p>
      <p className="text-sm text-blue-600">
        {vessel.status || "Unknown"}
      </p>
      {showDistance && vessel.distance_to_port && (
        <p className="text-sm text-green-600">
          📏 {vessel.distance_to_port} km from {selectedPort}
        </p>
      )}
    </div>
  );

  if (loading) {
    return (
      <div className="m-4 flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
          <p>Connecting to Frappe Realtime...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="m-4 space-y-6">
      {/* Header */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-gray-900">
            🇸🇦 Live Vessel Tracking - Saudi Arabia
          </h1>
          <div className="flex items-center space-x-4">
            <div className={`flex items-center ${connectionStatus ? 'text-green-600' : 'text-red-600'}`}>
              <div className={`w-3 h-3 rounded-full mr-2 ${connectionStatus ? 'bg-green-500' : 'bg-red-500'}`}></div>
              {connectionStatus ? '✅ Connected to Realtime' : '❌ Disconnected'}
            </div>
            <span className="text-sm text-gray-600">
              {vessels.length} vessels tracked
            </span>
            <button
              onClick={() => loadExistingVessels()}
              className="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600"
            >
              📚 Load DB
            </button>
            <button
              onClick={reconnect}
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              🔄 Reconnect
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Port Filter & Nearby Vessels */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              🏃 Select Saudi Port
            </label>
            <select
              value={selectedPort}
              onChange={(e) => setSelectedPort(e.target.value)}
              className="w-full p-3 border rounded-lg"
            >
              {ports.map(port => (
                <option key={port.name} value={port.name}>
                  {port.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <h3 className="text-lg font-semibold mb-3">
              🚢 Vessels Near {selectedPort} ({nearbyVessels.length})
            </h3>
            <div className="space-y-3 max-h-96 overflow-y-auto">
              {nearbyVessels.length > 0 ? (
                nearbyVessels.map((vessel, index) => (
                  <VesselCard key={vessel.mmsi || index} vessel={vessel} showDistance={true} />
                ))
              ) : (
                <div className="text-center py-8 text-gray-500">
                  <p>🔍 No vessels found near {selectedPort}</p>
                  <p className="text-sm mt-2">
                    {vessels.length > 0 ? "Try selecting another port" : "Waiting for vessel data..."}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Map */}
        <div className={`bg-white rounded-lg shadow p-4 ${isFullscreen ? 'fixed inset-4 z-50' : 'lg:col-span-2'}`}>
          <div className="flex justify-between items-center mb-3">
            <h3 className="text-lg font-semibold">🗺️ Live Vessel Map</h3>
            <div className="flex space-x-2">
              <button
                onClick={focusOnPort}
                className="px-3 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
              >
                Focus on {selectedPort}
              </button>
              <button
                onClick={() => {
                  if (mapInstance.current) {
                    mapInstance.current.setView([24.7136, 46.6753], 6);
                  }
                }}
                className="px-3 py-1 text-sm bg-gray-500 text-white rounded hover:bg-gray-600"
              >
                Reset View
              </button>
              <button
                onClick={toggleFullscreen}
                className="px-3 py-1 text-sm bg-purple-500 text-white rounded hover:bg-purple-600"
              >
                {isFullscreen ? '📱 Exit Fullscreen' : '🖥️ Fullscreen'}
              </button>
            </div>
          </div>
          <div 
            ref={mapRef} 
            className="w-full rounded-lg border bg-gray-100"
            style={{ 
              height: isFullscreen ? 'calc(100vh - 200px)' : '400px',
              minHeight: isFullscreen ? 'calc(100vh - 200px)' : '400px',
              position: 'relative',
              zIndex: 1
            }}
          >
            {!mapLoaded && (
              <div className="absolute inset-0 flex items-center justify-center bg-gray-100 rounded-lg">
                <div className="text-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
                  <p className="text-gray-600">Loading map...</p>
                </div>
              </div>
            )}
          </div>
          
          {/* Map Legend */}
          <div className="mt-4 p-3 bg-gray-50 rounded">
            <h4 className="text-sm font-medium mb-2">Legend</h4>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="flex items-center">
                <div className="w-3 h-3 bg-red-600 rounded-full mr-2"></div>
                <span>Ports</span>
              </div>
              <div className="flex items-center">
                <div className="w-3 h-3 bg-blue-500 rounded-full mr-2"></div>
                <span>Under way</span>
              </div>
              <div className="flex items-center">
                <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
                <span>At anchor</span>
              </div>
              <div className="flex items-center">
                <div className="w-3 h-3 bg-purple-500 rounded-full mr-2"></div>
                <span>Moored</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* All Vessels */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="text-lg font-semibold mb-3">
          🌊 All Tracked Vessels ({vessels.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-h-64 overflow-y-auto">
          {vessels.length > 0 ? (
            vessels.map((vessel, index) => (
              <VesselCard key={vessel.mmsi || index} vessel={vessel} />
            ))
          ) : (
            <div className="col-span-full text-center py-8 text-gray-500">
              <div className="space-y-3">
                <p className="text-lg">🛰️ Waiting for live vessel data...</p>
                <p className="text-sm">
                  {connectionStatus 
                    ? "Connected to Frappe Realtime AIS stream. Vessels will appear as they broadcast their positions."
                    : "Connection lost. Click Reconnect to try again."
                  }
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Vessel Detail Modal */}
      {selectedVessel && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full m-4">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-lg font-bold">
                🚢 {selectedVessel.vessel_name || `MMSI: ${selectedVessel.mmsi}`}
              </h3>
              <button 
                onClick={() => setSelectedVessel(null)}
                className="text-gray-500 hover:text-gray-700 text-xl"
              >
                ×
              </button>
            </div>
            
            <div className="space-y-3 text-sm">
              <div><strong>MMSI:</strong> {selectedVessel.mmsi}</div>
              <div><strong>Position:</strong> {selectedVessel.latitude?.toFixed(6)}, {selectedVessel.longitude?.toFixed(6)}</div>
              <div><strong>Speed:</strong> {selectedVessel.speed} knots</div>
              <div><strong>Course:</strong> {selectedVessel.course}°</div>
              <div><strong>Status:</strong> {selectedVessel.status}</div>
              {selectedVessel.vessel_name && <div><strong>Name:</strong> {selectedVessel.vessel_name}</div>}
              {selectedVessel.destination && <div><strong>Destination:</strong> {selectedVessel.destination}</div>}
              {selectedVessel.vessel_type && <div><strong>Type:</strong> {selectedVessel.vessel_type}</div>}
              <div><strong>Last Update:</strong> {new Date(selectedVessel.timestamp).toLocaleString()}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export function App() {
  return <VesselMap />;
}
