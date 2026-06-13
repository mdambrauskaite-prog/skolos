# VMI ir Sodros skolų dashboardas

## Paleidimas lokaliai
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy
Tinka Streamlit Community Cloud, Render, Railway arba vidinis serveris. Vartotojui reikės tik atsidaryti app nuorodą.

App automatiškai ima:
- VMI: `data.gov.lt` / `get.data.gov.lt` juridinių asmenų mokestinės nepriemokos duomenis
- Sodra: `https://sodra.lt/Failai/Skolos.zip`

Jei Sodra laikinai neatsisiunčia iš serverio, šoninėje juostoje galima įkelti `Skolos.zip` ranka.
