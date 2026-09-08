// ==============================================================================
// Genwizard ITSM — Native mongosh Seed Script for Identity Management & atr-mongo
// ==============================================================================
// Usage:
//   docker exec -i atr-mongo mongosh -u atr -p <password> --authenticationDatabase admin < scripts/seed_im_mongo.js
// Or from inside mongosh:
//   load("scripts/seed_im_mongo.js")
// ==============================================================================

// Target databases (seeds both nexus_itsm and im for maximum compatibility)
const targetDbs = ["nexus_itsm", "identity_management", "im_db"];

targetDbs.forEach(function(dbName) {
  const currentDb = db.getSiblingDB(dbName);
  print("\n========================================================");
  print(">>> Configuring Groups & DLs in database: " + dbName);
  print("========================================================");

  // 1. Core Groups with Attached Permissions
  const groupsToSeed = [
    {
      name: "IM_SAML",
      description: "Default SSO End-User Group for creating tickets, viewing own tickets, updating comments/worknotes, and viewing applications/projects.",
      permissions: JSON.stringify([
        "ticket_create",
        "ticket_read_own",
        "ticket_update",
        "applications_read",
        "projects_read"
      ]),
      active: true,
      created_at: new Date()
    },
    {
      name: "ATR_SAML",
      description: "Default SSO End-User Group (ATR SAML) for creating tickets, viewing own tickets, updating comments/worknotes, and viewing applications/projects.",
      permissions: JSON.stringify([
        "ticket_create",
        "ticket_read_own",
        "ticket_update",
        "applications_read",
        "projects_read"
      ]),
      active: true,
      created_at: new Date()
    },
    {
      name: "itsm_admin",
      description: "ITSM Platform Administrator Group with full management and operational permissions.",
      permissions: JSON.stringify([
        "admin_all",
        "ticket_create",
        "ticket_read",
        "ticket_update",
        "ticket_delete",
        "ticket_assign",
        "ticket_resolve",
        "ticket_close",
        "admin_routing",
        "admin_slas",
        "admin_config",
        "users_manage",
        "applications_read",
        "projects_read"
      ]),
      active: true,
      created_at: new Date()
    },
    {
      name: "itsm_user",
      description: "ITSM Support Fulfiller Group with queue assignment and ticket resolution permissions.",
      permissions: JSON.stringify([
        "ticket_create",
        "ticket_read",
        "ticket_update",
        "ticket_assign",
        "ticket_resolve",
        "applications_read",
        "projects_read"
      ]),
      active: true,
      created_at: new Date()
    },
    {
      name: "itsm_read",
      description: "ITSM Read-Only Group with read access to tickets, applications, and projects.",
      permissions: JSON.stringify([
        "ticket_read",
        "applications_read",
        "projects_read"
      ]),
      active: true,
      created_at: new Date()
    }
  ];

  const groupMap = {};

  // Seed into both custom_groups and groups collection
  ["custom_groups", "groups"].forEach(function(collName) {
    groupsToSeed.forEach(function(g) {
      const existing = currentDb[collName].findOne({ name: g.name });
      if (!existing) {
        // Auto-increment id simulation
        const lastDoc = currentDb[collName].find().sort({ id: -1 }).limit(1).toArray();
        const nextId = (lastDoc.length > 0 && lastDoc[0].id) ? lastDoc[0].id + 1 : 1;
        const toInsert = Object.assign({}, g, { id: nextId });
        currentDb[collName].insertOne(toInsert);
        groupMap[g.name] = nextId;
        print("  ✓ Created group [" + g.name + "] in collection [" + collName + "] with ID: " + nextId);
      } else {
        groupMap[g.name] = existing.id || existing._id;
        currentDb[collName].updateOne(
          { _id: existing._id },
          { $set: { permissions: g.permissions, description: g.description, active: true } }
        );
        print("  ✓ Refreshed group [" + g.name + "] permissions in [" + collName + "]");
      }
    });
  });

  // 2. Associate Existing Admin User with itsm_admin Group
  // (AD Groups and DLs can be configured post-installation directly in IM UI)
  ["users"].forEach(function(collName) {
    if (currentDb.getCollectionNames().includes(collName)) {
      const adminDoc = currentDb[collName].findOne({
        $or: [{ username: "admin" }, { role: "admin" }, { role: "administrator" }, { role: "itsm_admin" }]
      });
      if (adminDoc) {
        let userGroups = adminDoc.custom_groups || adminDoc.groups || [];
        if (!Array.isArray(userGroups)) {
          userGroups = [userGroups];
        }
        if (!userGroups.includes("itsm_admin")) {
          userGroups.push("itsm_admin");
        }
        currentDb[collName].updateOne(
          { _id: adminDoc._id },
          { $set: { role: "itsm_admin", custom_groups: userGroups, groups: userGroups } }
        );
        print("  ✓ Added [itsm_admin] group to existing admin user: " + (adminDoc.username || adminDoc.email || adminDoc._id));
      }
    }
  });

  // 3. Permissions Catalog Collection (if standalone permissions collection is used)
  const permCatalog = [
    { code: "ticket_create", category: "Tickets", description: "Create incidents and service requests" },
    { code: "ticket_read", category: "Tickets", description: "View incidents and service requests" },
    { code: "ticket_read_own", category: "Tickets", description: "View own created tickets" },
    { code: "ticket_update", category: "Tickets", description: "Update ticket status and work notes" },
    { code: "ticket_assign", category: "Tickets", description: "Assign tickets to groups or engineers" },
    { code: "ticket_resolve", category: "Tickets", description: "Resolve incidents and requests" },
    { code: "ticket_close", category: "Tickets", description: "Close or resolve incidents and requests" },
    { code: "ticket_delete", category: "Tickets", description: "Delete or archive ticket records" },
    { code: "admin_all", category: "Administration", description: "Full administrative control" },
    { code: "admin_routing", category: "Administration", description: "Manage 6-tier routing rules" },
    { code: "admin_slas", category: "Administration", description: "Configure SLA policies and calendars" },
    { code: "applications_read", category: "Administration", description: "View applications list" },
    { code: "projects_read", category: "Administration", description: "View projects list" }
  ];

  ["permissions", "permission_catalog"].forEach(function(collName) {
    if (currentDb.getCollectionNames().includes(collName)) {
      permCatalog.forEach(function(p) {
        currentDb[collName].updateOne(
          { code: p.code },
          { $set: p },
          { upsert: true }
        );
      });
      print("  ✓ Synchronized permissions catalog into [" + collName + "]");
    }
  });
});

// 3. Initialize ITSM Collections and Indexes in nexus_itsm
print("\n========================================================");
print(">>> Initializing Native ITSM Indexes in nexus_itsm");
print("========================================================");
const itsmDb = db.getSiblingDB("nexus_itsm");

const collectionsAndIndexes = [
  { name: "incidents", index: { ticket_number: 1 }, unique: true },
  { name: "incidents", index: { project_id: 1, state: 1 }, unique: false },
  { name: "service_requests", index: { ticket_number: 1 }, unique: true },
  { name: "change_requests", index: { change_number: 1 }, unique: true },
  { name: "users", index: { username: 1 }, unique: true },
  { name: "users", index: { email: 1 }, unique: false },
  { name: "projects", index: { code: 1 }, unique: true },
  { name: "applications", index: { project_id: 1, name: 1 }, unique: false },
  { name: "assignment_groups", index: { name: 1 }, unique: true },
  { name: "sla_policies", index: { project_id: 1, assignment_group_id: 1, active: 1 }, unique: false },
  { name: "audit_logs", index: { entity_type: 1, entity_id: 1, created_at: -1 }, unique: false }
];

collectionsAndIndexes.forEach(function(ci) {
  try {
    itsmDb[ci.name].createIndex(ci.index, { unique: ci.unique, background: true });
    print("  ✓ Ensured index on " + ci.name + ": " + JSON.stringify(ci.index));
  } catch (e) {
    print("  - Index notice on " + ci.name + ": " + e.message);
  }
});

print("\n>>> MongoDB Identity Management & ITSM initialization complete!\n");
