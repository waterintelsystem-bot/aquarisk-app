st.divider()
c_save, c_load = st.columns(2)

with c_save:
    if st.button("💾 SAUVEGARDER CET AUDIT EN BASE", type="primary"):
        msg = utils.save_audit_to_db(st.session_state)
        st.toast(msg, icon="✅")
        st.balloons()

with c_load:
    st.write("📂 **Historique des Audits**")
    try:
        df_history = utils.load_all_audits()
        if not df_history.empty:
            st.dataframe(df_history, hide_index=True)
        else:
            st.info("La base de données est vide.")
    except: st.write("Erreur lecture DB")
        
